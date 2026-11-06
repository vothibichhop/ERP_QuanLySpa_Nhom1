from collections import defaultdict

from odoo import api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


SPA_INVENTORY_TYPES = [
    ('equipment', 'Thiết bị, máy móc'),
    ('retail', 'Sản phẩm bán'),
    ('service_material', 'Nguyên vật liệu dịch vụ'),
]


class ProductTemplate(models.Model):
    _inherit = 'product.template'

    spa_inventory_type = fields.Selection(
        SPA_INVENTORY_TYPES,
        string='Loại hàng trong kho',
        default='retail',
        copy=False,
        index=True,
    )
    spa_stock_status = fields.Selection(
        [
            ('available', 'Còn hàng'),
            ('low', 'Sắp hết'),
            ('out_of_stock', 'Hết hàng'),
        ],
        string='Tình trạng kho',
        compute='_compute_spa_stock_status',
    )
    spa_expiration_date = fields.Date(
        string='Hạn sử dụng',
        help=(
            'Ngày hết hạn áp dụng cho mặt hàng này. Nếu các lô nhập có hạn '
            'khác nhau, ngày này không thay thế việc theo dõi hạn theo từng lô.'
        ),
    )
    spa_service_material_ids = fields.One2many(
        'spa.service.material',
        'service_id',
        string='Định lượng nguyên vật liệu',
    )
    spa_combo_material_summary = fields.Text(
        string='Định lượng nguyên vật liệu',
        compute='_compute_spa_combo_material_summary',
    )

    @api.depends('qty_available', 'spa_inventory_type')
    def _compute_spa_stock_status(self):
        for product in self:
            if product.qty_available <= 0:
                product.spa_stock_status = 'out_of_stock'
            elif (
                product.spa_inventory_type != 'equipment'
                and product.qty_available <= 10
            ):
                product.spa_stock_status = 'low'
            else:
                product.spa_stock_status = 'available'

    @api.depends(
        'type',
        'combo_ids',
        'combo_ids.combo_item_ids.product_id.product_tmpl_id',
        'combo_ids.combo_item_ids.product_id.product_tmpl_id.spa_service_material_ids',
        'combo_ids.combo_item_ids.product_id.product_tmpl_id.spa_service_material_ids.quantity',
        'combo_ids.combo_item_ids.product_id.product_tmpl_id.spa_service_material_ids.product_id',
        'combo_ids.combo_item_ids.product_id.product_tmpl_id.spa_service_material_ids.uom_id',
    )
    def _compute_spa_combo_material_summary(self):
        for product in self:
            if product.type != 'combo' or not product.combo_ids:
                product.spa_combo_material_summary = False
                continue

            combo_choices = product.combo_ids.sorted(
                key=lambda combo: (combo.sequence, combo.id)
            )
            has_alternatives = any(
                len(combo.combo_item_ids) > 1
                for combo in combo_choices
            )
            lines = []

            if not has_alternatives:
                quantity_by_material = defaultdict(float)
                materials_by_product = {}
                unconfigured_services = []
                for combo_choice in combo_choices:
                    for item in combo_choice.combo_item_ids:
                        service = item.product_id.product_tmpl_id
                        if service.type != 'service':
                            continue
                        if not service.spa_service_material_ids:
                            unconfigured_services.append(service.display_name)
                        for material in service.spa_service_material_ids:
                            product_id = material.product_id.id
                            quantity_by_material[product_id] += (
                                material.quantity
                            )
                            materials_by_product[product_id] = (
                                material.product_id
                            )

                for product_id in sorted(materials_by_product):
                    material_product = materials_by_product[product_id]
                    quantity = quantity_by_material[product_id]
                    lines.append(
                        '%s: %s %s'
                        % (
                            material_product.display_name,
                            format(quantity, 'g'),
                            material_product.uom_id.name,
                        )
                    )
                if unconfigured_services:
                    lines.append(
                        'Chưa thiết lập định lượng: %s'
                        % ', '.join(unconfigured_services)
                    )
            else:
                for combo_choice in combo_choices:
                    lines.append('%s:' % combo_choice.name)
                    for item in combo_choice.combo_item_ids:
                        service = item.product_id.product_tmpl_id
                        if service.type != 'service':
                            continue
                        lines.append('  %s' % service.display_name)
                        if service.spa_service_material_ids:
                            for material in service.spa_service_material_ids:
                                lines.append(
                                    '    %s: %s %s'
                                    % (
                                        material.product_id.display_name,
                                        format(material.quantity, 'g'),
                                        material.uom_id.name,
                                    )
                                )
                        else:
                            lines.append('    Chưa thiết lập định lượng.')

            product.spa_combo_material_summary = (
                '\n'.join(lines)
                if lines
                else 'Các dịch vụ thành phần chưa có định lượng.'
            )

    @api.constrains('spa_inventory_type', 'is_storable')
    def _check_spa_inventory_type(self):
        material_lines = self.env['spa.service.material'].sudo().search([
            ('product_id.product_tmpl_id', 'in', self.ids),
        ])
        for line in material_lines:
            if (
                not line.product_id.is_storable
                or line.product_id.product_tmpl_id.spa_inventory_type
                != 'service_material'
            ):
                raise ValidationError(
                    'Sản phẩm đang được định lượng cho dịch vụ phải là hàng '
                    'tồn kho thuộc loại Nguyên vật liệu dịch vụ.'
                )


class SpaServiceMaterial(models.Model):
    _name = 'spa.service.material'
    _description = 'Định lượng nguyên vật liệu dịch vụ Spa'
    _order = 'service_id, id'

    service_id = fields.Many2one(
        'product.template',
        string='Dịch vụ',
        required=True,
        ondelete='cascade',
        domain=[('type', '=', 'service')],
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Nguyên vật liệu',
        required=True,
        ondelete='restrict',
        domain=[
            ('is_storable', '=', True),
            ('product_tmpl_id.spa_inventory_type', '=', 'service_material'),
        ],
        index=True,
    )
    quantity = fields.Float(
        string='Định lượng',
        required=True,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        'uom.uom',
        string='Đơn vị tính',
        related='product_id.uom_id',
        readonly=True,
    )

    _sql_constraints = [
        (
            'service_product_unique',
            'unique(service_id, product_id)',
            'Mỗi nguyên vật liệu chỉ được khai báo một lần cho mỗi dịch vụ.',
        ),
    ]

    @api.constrains('service_id', 'product_id', 'quantity')
    def _check_service_material(self):
        for line in self:
            if line.service_id.type != 'service':
                raise ValidationError(
                    'Chỉ có thể khai báo định lượng cho dịch vụ Spa.'
                )
            if (
                not line.product_id.is_storable
                or line.product_id.product_tmpl_id.spa_inventory_type
                != 'service_material'
            ):
                raise ValidationError(
                    'Hãy chọn sản phẩm tồn kho thuộc loại Nguyên vật liệu dịch vụ.'
                )
            if line.quantity <= 0:
                raise ValidationError('Định lượng phải lớn hơn 0.')


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    spa_receipt_date = fields.Date(
        string='Ngày nhập',
        required=True,
        default=fields.Date.context_today,
        copy=False,
    )
    spa_receipt_employee_id = fields.Many2one(
        'hr.employee',
        string='Nhân viên lập phiếu',
        default=lambda self: self._default_spa_receipt_employee(),
        check_company=True,
        copy=False,
    )
    spa_receipt_invoice_code = fields.Char(
        string='Mã hóa đơn',
        copy=False,
    )
    spa_receipt_total_amount = fields.Monetary(
        string='Tổng tiền',
        currency_field='company_currency_id',
        default=0,
        copy=False,
        help='Tổng tiền theo hóa đơn nhập kho.',
    )
    spa_receipt_status = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('confirmed', 'Đã xác nhận'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái phiếu nhập',
        compute='_compute_spa_receipt_status',
    )
    company_currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )

    spa_appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch dịch vụ Spa',
        copy=False,
        index=True,
        ondelete='set null',
    )

    @api.model
    def _default_spa_receipt_employee(self):
        return self.env['hr.employee'].sudo().search([
            ('user_id', '=', self.env.uid),
            ('company_id', 'in', [self.env.company.id, False]),
            ('active', '=', True),
        ], limit=1).id

    @api.depends('state')
    def _compute_spa_receipt_status(self):
        for picking in self:
            if picking.state == 'done':
                picking.spa_receipt_status = 'confirmed'
            elif picking.state == 'cancel':
                picking.spa_receipt_status = 'cancelled'
            else:
                picking.spa_receipt_status = 'draft'

    def _sanity_check(self, separate_pickings=True):
        for picking in self.filtered(
            lambda record: record.picking_type_code == 'incoming'
        ):
            for move in picking.move_ids.filtered(
                lambda record: record.product_id.tracking != 'none'
                and record.spa_lot_name
            ):
                if move.product_id.tracking == 'serial' and float_compare(
                    move.quantity,
                    1,
                    precision_rounding=move.product_uom.rounding,
                ) != 0:
                    raise UserError(
                        'Sản phẩm theo dõi số sê-ri phải có số lượng bằng 1 '
                        'trên mỗi dòng nhập.'
                    )

                conflicting_lines = move.move_line_ids.filtered(
                    lambda line: (
                        line.lot_id and line.lot_id.name != move.spa_lot_name
                    ) or (
                        line.lot_name
                        and line.lot_name != move.spa_lot_name
                    )
                )
                if conflicting_lines:
                    raise UserError(
                        'Mã lô trên dòng sản phẩm không khớp với chi tiết '
                        'thao tác kho.'
                    )
                move.move_line_ids.filtered(
                    lambda line: not line.lot_id
                ).write({'lot_name': move.spa_lot_name})

        return super()._sanity_check(separate_pickings=separate_pickings)

    def button_validate(self):
        for picking in self.filtered(
            lambda record: record.picking_type_code == 'incoming'
            and record.spa_receipt_date
            and record.state not in ('done', 'cancel')
        ):
            picking.scheduled_date = fields.Datetime.to_datetime(
                picking.spa_receipt_date
            )
        return super().button_validate()


class StockMove(models.Model):
    _inherit = 'stock.move'

    spa_lot_name = fields.Char(
        string='Mã lô',
        copy=False,
        help='Mã lô được dùng khi sản phẩm có bật theo dõi lô.',
    )


class SpaAppointment(models.Model):
    _inherit = 'spa.appointment'

    spa_material_picking_ids = fields.One2many(
        'stock.picking',
        'spa_appointment_id',
        string='Phiếu xuất nguyên vật liệu',
        readonly=True,
    )

    def _get_spa_consumed_services(self):
        self.ensure_one()
        services = []
        if self.appointment_line_ids:
            for line in self.appointment_line_ids:
                if line.product_id.type == 'service':
                    services.append(line.product_id)
                elif line.product_id.type == 'combo':
                    for choice in line.combo_choice_ids:
                        service = (
                            choice.combo_item_id.product_id.product_tmpl_id
                        )
                        if service.type == 'service':
                            services.append(service)
        elif self.service_product_id.type == 'service':
            services.append(self.service_product_id)
        elif self.service_id:
            legacy_services = self.env['product.template'].search([
                ('name', '=', self.service_id.name),
                ('type', '=', 'service'),
            ], limit=2)
            if len(legacy_services) == 1:
                services.append(legacy_services)
        return services

    def _get_spa_service_material_quantities(self):
        self.ensure_one()
        quantity_by_product = defaultdict(float)
        for service in self._get_spa_consumed_services():
            for material in service.spa_service_material_ids:
                quantity_by_product[material.product_id.id] += (
                    material.quantity * self.guest_count
                )
        return quantity_by_product

    def _consume_spa_service_materials(self, quantity_by_product=None):
        self.ensure_one()
        if self.sudo().spa_material_picking_ids.filtered(
            lambda picking: picking.state == 'done'
        ):
            raise ValidationError(
                'Nguyên vật liệu của lịch này đã được xuất kho.'
            )

        if quantity_by_product is None:
            quantity_by_product = (
                self._get_spa_service_material_quantities()
            )
        quantity_by_product = {
            product_id: quantity
            for product_id, quantity in quantity_by_product.items()
            if quantity > 0
        }
        if not quantity_by_product:
            return

        products = self.env['product.product'].browse(
            list(quantity_by_product)
        )
        company = self.env.company
        warehouse = self.env['stock.warehouse'].sudo().search([
            ('company_id', '=', company.id),
        ], limit=1)
        if not warehouse or not warehouse.lot_stock_id:
            raise UserError(
                'Hãy cấu hình kho nội bộ cho công ty trước khi hoàn thành dịch vụ.'
            )
        if not warehouse.int_type_id:
            raise UserError(
                'Hãy cấu hình loại hoạt động chuyển kho nội bộ trước khi '
                'hoàn thành dịch vụ.'
            )

        source_location = warehouse.lot_stock_id
        quant_model = self.env['stock.quant'].sudo()
        shortages = []
        production_location = False
        for product in products:
            quantity = quantity_by_product[product.id]
            available = quant_model._get_available_quantity(
                product.with_company(company),
                source_location,
            )
            if float_compare(
                available,
                quantity,
                precision_rounding=product.uom_id.rounding,
            ) < 0:
                shortages.append(
                    '%s (cần %s %s, khả dụng %s)'
                    % (
                        product.display_name,
                        quantity,
                        product.uom_id.display_name,
                        available,
                    )
                )
            product_production_location = (
                product.sudo().with_company(
                    company
                ).property_stock_production
            )
            if not product_production_location:
                raise UserError(
                    'Chưa cấu hình vị trí sản xuất để xuất nguyên vật liệu.'
                )
            if production_location and (
                production_location != product_production_location
            ):
                raise UserError(
                    'Các nguyên vật liệu của dịch vụ đang dùng vị trí sản xuất '
                    'khác nhau. Hãy cấu hình cùng một vị trí cho công ty.'
                )
            production_location = product_production_location

        if shortages:
            raise UserError(
                'Không đủ nguyên vật liệu để hoàn thành dịch vụ:\n%s'
                % '\n'.join(shortages)
            )

        picking = self.env['stock.picking'].sudo().create({
            'picking_type_id': warehouse.int_type_id.id,
            'location_id': source_location.id,
            'location_dest_id': production_location.id,
            'origin': self.name,
            'company_id': company.id,
            'spa_appointment_id': self.id,
        })
        moves = self.env['stock.move'].sudo().create([
            {
                'name': product.display_name,
                'product_id': product.id,
                'product_uom_qty': quantity_by_product[product.id],
                'product_uom': product.uom_id.id,
                'location_id': source_location.id,
                'location_dest_id': production_location.id,
                'company_id': company.id,
                'origin': self.name,
                'picking_id': picking.id,
            }
            for product in products
        ])
        picking.action_confirm()
        picking.action_assign()

        unreserved_moves = moves.filtered(
            lambda move: float_compare(
                move.quantity,
                move.product_uom_qty,
                precision_rounding=move.product_uom.rounding,
            ) < 0
        )
        if unreserved_moves:
            raise UserError(
                'Không thể giữ đủ nguyên vật liệu trong kho để hoàn thành '
                'dịch vụ. Hãy kiểm tra tồn khả dụng rồi thử lại.'
            )
        for move in moves:
            move.quantity = move.product_uom_qty
            move.picked = True
        picking._action_done()
