from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class SpaEquipmentAsset(models.Model):
    _name = 'spa.equipment.asset'
    _description = 'Thiết bị Spa'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'asset_code'
    _order = 'asset_code'
    _check_company_auto = True

    @api.model
    def _default_asset_code(self):
        code = self.env['ir.sequence'].next_by_code('spa.equipment.asset')
        if not code:
            raise UserError(_('Chưa cấu hình chuỗi mã thiết bị Spa.'))
        return code

    asset_code = fields.Char(
        string='Mã tài sản',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self._default_asset_code(),
        tracking=True,
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Sản phẩm thiết bị',
        required=True,
        domain=[
            ('is_storable', '=', True),
            ('product_tmpl_id.spa_inventory_type', '=', 'equipment'),
        ],
        check_company=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    serial_number = fields.Char(
        string='Số sê-ri',
        copy=False,
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Công ty',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    purchase_date = fields.Date(string='Ngày mua', tracking=True)
    warranty_end_date = fields.Date(string='Ngày hết bảo hành', tracking=True)
    vendor_id = fields.Many2one(
        'res.partner',
        string='Nhà cung cấp',
        check_company=True,
        domain=[('supplier_rank', '>', 0)],
        ondelete='restrict',
    )
    location_id = fields.Many2one(
        'stock.location',
        string='Vị trí sử dụng',
        domain=[('usage', '=', 'internal')],
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    status = fields.Selection(
        [
            ('available', 'Sẵn sàng sử dụng'),
            ('in_use', 'Đang sử dụng'),
            ('reported', 'Đã báo hỏng'),
            ('waiting_repair', 'Chờ sửa chữa'),
            ('in_repair', 'Đang sửa chữa'),
            ('scrapped', 'Đã thanh lý'),
        ],
        string='Tình trạng',
        required=True,
        default='available',
        copy=False,
        tracking=True,
        index=True,
    )
    repair_ids = fields.One2many(
        'spa.equipment.repair',
        'asset_id',
        string='Lịch sử báo hỏng',
        readonly=True,
    )
    repair_count = fields.Integer(
        string='Số lần báo hỏng',
        compute='_compute_repair_count',
    )
    note = fields.Text(string='Ghi chú')

    _sql_constraints = [
        (
            'asset_code_unique',
            'unique(asset_code)',
            'Mã tài sản đã tồn tại.',
        ),
        (
            'serial_number_unique',
            'unique(serial_number)',
            'Số sê-ri đã được gán cho một thiết bị khác.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('status', 'available') not in ('available', 'in_use'):
                raise ValidationError(
                    'Thiết bị mới chỉ có thể ở trạng thái sẵn sàng hoặc đang sử dụng.'
                )
        return super().create(vals_list)

    @api.depends('repair_ids')
    def _compute_repair_count(self):
        for asset in self:
            asset.repair_count = len(asset.repair_ids)

    @api.constrains('product_id')
    def _check_equipment_product(self):
        for asset in self:
            if (
                not asset.product_id.is_storable
                or asset.product_id.product_tmpl_id.spa_inventory_type
                != 'equipment'
            ):
                raise ValidationError(
                    'Chỉ được chọn sản phẩm tồn kho thuộc loại Thiết bị, máy móc.'
                )

    @api.constrains('purchase_date', 'warranty_end_date')
    def _check_warranty_dates(self):
        for asset in self:
            if (
                asset.purchase_date
                and asset.warranty_end_date
                and asset.warranty_end_date < asset.purchase_date
            ):
                raise ValidationError(
                    'Ngày hết bảo hành không được trước ngày mua.'
                )

    def action_view_repairs(self):
        self.ensure_one()
        action = self.env['ir.actions.actions']._for_xml_id(
            'spa.action_spa_equipment_repairs'
        )
        action['domain'] = [('asset_id', '=', self.id)]
        action['context'] = {'default_asset_id': self.id}
        return action

    def action_report_breakdown(self):
        self.ensure_one()
        if self.status not in ('available', 'in_use'):
            raise UserError(
                'Chỉ có thể báo hỏng thiết bị đang sẵn sàng hoặc đang sử dụng.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Báo hỏng thiết bị',
            'res_model': 'spa.equipment.repair',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_asset_id': self.id},
        }

    def write(self, vals):
        if 'status' in vals:
            raise UserError(
                'Hãy cập nhật tình trạng thiết bị bằng các nút xử lý.'
            )
        return super().write(vals)

    def _write_status(self, status):
        return super(SpaEquipmentAsset, self).write({'status': status})

    def action_mark_in_use(self):
        if any(asset.status != 'available' for asset in self):
            raise UserError(
                'Chỉ thiết bị sẵn sàng mới có thể chuyển sang đang sử dụng.'
            )
        self._write_status('in_use')

    def action_mark_available(self):
        if any(asset.status != 'in_use' for asset in self):
            raise UserError(
                'Chỉ thiết bị đang sử dụng mới có thể chuyển sang sẵn sàng.'
            )
        self._write_status('available')


class SpaEquipmentRepair(models.Model):
    _name = 'spa.equipment.repair'
    _description = 'Phiếu báo hỏng thiết bị Spa'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _rec_name = 'name'
    _order = 'reported_at desc, id desc'
    _check_company_auto = True

    @api.model
    def _default_repair_name(self):
        name = self.env['ir.sequence'].next_by_code(
            'spa.equipment.repair'
        )
        if not name:
            raise UserError(_('Chưa cấu hình chuỗi mã phiếu báo hỏng thiết bị.'))
        return name

    name = fields.Char(
        string='Mã phiếu',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self._default_repair_name(),
        index=True,
    )
    asset_id = fields.Many2one(
        'spa.equipment.asset',
        string='Thiết bị',
        required=True,
        check_company=True,
        ondelete='restrict',
        index=True,
        tracking=True,
    )
    company_id = fields.Many2one(
        'res.company',
        related='asset_id.company_id',
        store=True,
        readonly=True,
        index=True,
    )
    reported_at = fields.Datetime(
        string='Thời điểm báo hỏng',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    reporter_id = fields.Many2one(
        'res.users',
        string='Người báo hỏng',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    assigned_employee_id = fields.Many2one(
        'hr.employee',
        string='Nhân viên xử lý',
        check_company=True,
        ondelete='restrict',
        tracking=True,
    )
    priority = fields.Selection(
        [
            ('0', 'Bình thường'),
            ('1', 'Ưu tiên'),
            ('2', 'Khẩn cấp'),
        ],
        string='Mức độ ưu tiên',
        default='0',
        required=True,
        tracking=True,
    )
    description = fields.Text(
        string='Mô tả sự cố',
        required=True,
        tracking=True,
    )
    state = fields.Selection(
        [
            ('reported', 'Đã báo hỏng'),
            ('waiting', 'Chờ sửa chữa'),
            ('in_repair', 'Đang sửa chữa'),
            ('repaired', 'Đã sửa xong'),
            ('scrapped', 'Đã thanh lý'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        required=True,
        default='reported',
        copy=False,
        tracking=True,
        index=True,
    )
    previous_asset_status = fields.Selection(
        [
            ('available', 'Sẵn sàng sử dụng'),
            ('in_use', 'Đang sử dụng'),
        ],
        string='Tình trạng trước khi hỏng',
        required=True,
        readonly=True,
        copy=False,
    )
    vendor_id = fields.Many2one(
        'res.partner',
        string='Đơn vị sửa chữa',
        check_company=True,
        domain=[('supplier_rank', '>', 0)],
        ondelete='restrict',
    )
    sent_for_repair_date = fields.Date(string='Ngày gửi sửa')
    repaired_date = fields.Date(
        string='Ngày hoàn tất',
        readonly=True,
        copy=False,
    )
    repair_cost = fields.Monetary(
        string='Chi phí sửa chữa',
        currency_field='currency_id',
        default=0,
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    resolution = fields.Text(string='Kết quả xử lý')

    _sql_constraints = [
        (
            'repair_name_unique',
            'unique(name)',
            'Mã phiếu báo hỏng đã tồn tại.',
        ),
        (
            'repair_cost_nonnegative',
            'check(repair_cost >= 0)',
            'Chi phí sửa chữa không được âm.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals = []
        seen_asset_ids = set()
        for vals in vals_list:
            vals = dict(vals)
            asset = self.env['spa.equipment.asset'].browse(
                vals.get('asset_id')
            ).exists()
            if not asset:
                raise ValidationError('Vui lòng chọn thiết bị cần báo hỏng.')
            if asset.id in seen_asset_ids:
                raise UserError(
                    'Không thể tạo nhiều phiếu đang mở cho cùng một thiết bị.'
                )
            seen_asset_ids.add(asset.id)
            if asset.status not in ('available', 'in_use'):
                raise UserError(
                    'Thiết bị này đang có sự cố hoặc đã thanh lý.'
                )
            if self.search_count([
                ('asset_id', '=', asset.id),
                ('state', 'in', ('reported', 'waiting', 'in_repair')),
            ]):
                raise UserError(
                    'Thiết bị đã có phiếu báo hỏng chưa được xử lý xong.'
                )
            vals['previous_asset_status'] = asset.status
            vals['state'] = 'reported'
            prepared_vals.append(vals)

        repairs = super().create(prepared_vals)
        for repair in repairs:
            repair.asset_id._write_status('reported')
        return repairs

    def write(self, vals):
        protected_fields = {'asset_id', 'state', 'previous_asset_status'}
        if protected_fields.intersection(vals):
            raise UserError(
                'Không thể sửa trực tiếp thiết bị hoặc trạng thái phiếu báo hỏng.'
            )
        return super().write(vals)

    def _write_state(self, vals):
        return super(SpaEquipmentRepair, self).write(vals)

    @api.constrains('asset_id')
    def _check_asset_product(self):
        for repair in self:
            if (
                not repair.asset_id.product_id.is_storable
                or repair.asset_id.product_id.product_tmpl_id.spa_inventory_type
                != 'equipment'
            ):
                raise ValidationError(
                    'Phiếu báo hỏng phải liên kết với một thiết bị trong kho.'
                )

    def _set_state(self, new_state, asset_status):
        for repair in self:
            if repair.state not in ('reported', 'waiting', 'in_repair'):
                raise UserError(
                    'Phiếu báo hỏng đã kết thúc, không thể cập nhật tiếp.'
                )
        self._write_state({'state': new_state})
        self.mapped('asset_id')._write_status(asset_status)

    def action_mark_waiting(self):
        if any(repair.state != 'reported' for repair in self):
            raise UserError(
                'Chỉ phiếu mới báo hỏng mới có thể chuyển sang chờ sửa chữa.'
            )
        self._set_state('waiting', 'waiting_repair')

    def action_start_repair(self):
        if any(repair.state not in ('reported', 'waiting') for repair in self):
            raise UserError(
                'Phiếu phải ở trạng thái đã báo hỏng hoặc chờ sửa chữa.'
            )
        self._set_state('in_repair', 'in_repair')

    def action_mark_repaired(self):
        if any(repair.state != 'in_repair' for repair in self):
            raise UserError(
                'Chỉ có thể hoàn tất sửa chữa khi thiết bị đang được sửa.'
            )
        today = fields.Date.context_today(self)
        self._write_state({
            'state': 'repaired',
            'repaired_date': today,
        })
        for repair in self:
            repair.asset_id._write_status(repair.previous_asset_status)

    def action_scrap(self):
        if any(repair.state not in ('reported', 'waiting', 'in_repair') for repair in self):
            raise UserError(
                'Phiếu báo hỏng đã kết thúc, không thể thanh lý thiết bị.'
            )
        self._set_state('scrapped', 'scrapped')

    def action_cancel(self):
        if any(repair.state not in ('reported', 'waiting') for repair in self):
            raise UserError(
                'Chỉ có thể hủy phiếu mới báo hỏng hoặc đang chờ sửa chữa.'
            )
        self._write_state({'state': 'cancelled'})
        for repair in self:
            repair.asset_id._write_status(repair.previous_asset_status)

    @api.constrains('repair_cost')
    def _check_repair_cost(self):
        for repair in self:
            if repair.repair_cost < 0:
                raise ValidationError(
                    'Chi phí sửa chữa không được âm.'
                )


class SpaEquipmentBreakdownReport(models.Model):
    _name = 'spa.equipment.breakdown.report'
    _description = 'Phiếu báo hỏng thiết bị Spa'
    _order = 'reported_at desc, id desc'

    @api.model
    def _default_report_name(self):
        name = self.env['ir.sequence'].next_by_code(
            'spa.equipment.breakdown.report'
        )
        if not name:
            raise UserError(_('Chưa cấu hình chuỗi mã phiếu báo hỏng thiết bị.'))
        return name

    name = fields.Char(
        string='Mã phiếu',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: self._default_report_name(),
        index=True,
    )
    product_id = fields.Many2one(
        'product.product',
        string='Thiết bị, máy móc',
        required=True,
        domain=[
            ('is_storable', '=', True),
            ('product_tmpl_id.spa_inventory_type', '=', 'equipment'),
        ],
        ondelete='restrict',
        index=True,
    )
    reported_at = fields.Datetime(
        string='Thời điểm báo hỏng',
        required=True,
        default=fields.Datetime.now,
        readonly=True,
        index=True,
    )
    reporter_id = fields.Many2one(
        'res.users',
        string='Người báo hỏng',
        required=True,
        default=lambda self: self.env.user,
        readonly=True,
    )
    priority = fields.Selection(
        [
            ('0', 'Bình thường'),
            ('1', 'Ưu tiên'),
            ('2', 'Khẩn cấp'),
        ],
        string='Mức độ ưu tiên',
        default='0',
        required=True,
    )
    description = fields.Text(
        string='Mô tả sự cố',
        required=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Chưa gửi'),
            ('submitted', 'Đã gửi'),
        ],
        string='Trạng thái',
        required=True,
        default='draft',
        readonly=True,
        copy=False,
        index=True,
    )

    _sql_constraints = [
        (
            'breakdown_report_name_unique',
            'unique(name)',
            'Mã phiếu báo hỏng đã tồn tại.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        prepared_vals = []
        for vals in vals_list:
            vals = dict(vals)
            if vals.get('state', 'draft') != 'draft':
                raise UserError('Phiếu báo hỏng mới phải ở trạng thái chưa gửi.')
            vals['state'] = 'draft'
            prepared_vals.append(vals)
        return super().create(prepared_vals)

    @api.constrains('product_id')
    def _check_equipment_product(self):
        for report in self:
            if (
                not report.product_id.is_storable
                or report.product_id.product_tmpl_id.spa_inventory_type
                != 'equipment'
            ):
                raise ValidationError(
                    'Chỉ được báo hỏng sản phẩm thuộc danh mục Thiết bị, máy móc.'
                )

    def write(self, vals):
        if 'state' in vals:
            raise UserError('Hãy gửi phiếu báo hỏng bằng nút Gửi phiếu.')
        if any(report.state == 'submitted' for report in self):
            raise UserError('Không thể sửa phiếu báo hỏng đã gửi.')
        return super().write(vals)

    def action_submit(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError('Phiếu báo hỏng này đã được gửi.')
        super(SpaEquipmentBreakdownReport, self).write({
            'state': 'submitted',
        })
        return self.env['ir.actions.actions']._for_xml_id(
            'spa.action_spa_equipment_breakdown_reports'
        )
