from odoo import api, fields, models, _
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tools.float_utils import float_compare


class SpaReturnRequest(models.Model):
    _name = 'spa.return.request'
    _description = 'Yêu cầu trả hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(
        string='Mã yêu cầu',
        required=True,
        copy=False,
        readonly=True,
        default='/',
    )
    order_id = fields.Many2one(
        'sale.order',
        string='Đơn bán hàng',
        required=True,
        index=True,
        ondelete='restrict',
    )
    partner_id = fields.Many2one(
        related='order_id.partner_id',
        string='Khách hàng',
        store=True,
    )
    delivery_picking_id = fields.Many2one(
        'stock.picking',
        string='Phiếu xuất kho',
        ondelete='restrict',
    )
    returnable_picking_ids = fields.Many2many(
        'stock.picking',
        compute='_compute_returnable_picking_ids',
        compute_sudo=True,
    )
    line_ids = fields.One2many(
        'spa.return.request.line',
        'request_id',
        string='Sản phẩm trả',
        copy=True,
    )
    reason = fields.Text(string='Lý do trả hàng', required=True)
    requested_by = fields.Many2one(
        'res.users',
        string='Người yêu cầu',
        required=True,
        readonly=True,
        default=lambda self: self.env.user,
    )
    approver_id = fields.Many2one(
        'res.users',
        string='Người duyệt',
        readonly=True,
        copy=False,
    )
    state = fields.Selection(
        [
            ('draft', 'Nháp'),
            ('submitted', 'Chờ duyệt'),
            ('approved', 'Đã duyệt'),
            ('refused', 'Từ chối'),
            ('cancelled', 'Đã hủy'),
        ],
        string='Trạng thái',
        required=True,
        default='draft',
        copy=False,
        index=True,
        tracking=True,
    )
    return_picking_id = fields.Many2one(
        'stock.picking',
        string='Phiếu nhập hàng trả',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    invoice_id = fields.Many2one(
        'account.move',
        string='Hóa đơn cần hoàn',
        copy=False,
        domain="[('partner_id', '=', partner_id), ('move_type', '=', 'out_invoice'), "
               "('state', '=', 'posted')]",
    )
    credit_note_id = fields.Many2one(
        'account.move',
        string='Credit note',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    return_state = fields.Selection(
        [
            ('not_created', 'Chưa tạo phiếu nhập trả'),
            ('draft', 'Nháp'),
            ('waiting', 'Chờ xử lý'),
            ('confirmed', 'Đã xác nhận'),
            ('assigned', 'Sẵn sàng'),
            ('done', 'Đã nhận'),
            ('cancel', 'Đã hủy'),
        ],
        compute='_compute_return_state',
        string='Trạng thái nhận hàng',
    )
    return_received = fields.Boolean(
        string='Đã nhận đủ hàng trả',
        compute='_compute_return_received',
        compute_sudo=True,
    )
    return_product_summary = fields.Char(
        string='Sản phẩm trả',
        compute='_compute_return_line_summaries',
    )
    return_quantity_summary = fields.Char(
        string='Số lượng trả',
        compute='_compute_return_line_summaries',
    )
    needs_delivery_selection = fields.Boolean(
        compute='_compute_returnable_picking_selection',
    )
    needs_invoice_selection = fields.Boolean(
        compute='_compute_needs_invoice_selection',
    )
    order_product_ids = fields.Many2many(
        'product.product',
        compute='_compute_order_product_ids',
        compute_sudo=True,
    )
    can_register_refund_payment = fields.Boolean(
        string='Có thể đăng ký thanh toán hoàn',
        compute='_compute_can_register_refund_payment',
        help='Credit note đã ghi sổ và còn số dư chưa được thanh toán.',
    )
    refund_confirmed = fields.Boolean(
        string='Đã hoàn tiền',
        readonly=True,
        copy=False,
        tracking=True,
        help='Kế toán xác nhận sau khi tiền thực tế đã được hoàn cho khách.',
    )
    refund_confirmed_by = fields.Many2one(
        'res.users',
        string='Người xác nhận hoàn tiền',
        readonly=True,
        copy=False,
    )
    refund_confirmed_at = fields.Datetime(
        string='Thời điểm xác nhận hoàn tiền',
        readonly=True,
        copy=False,
    )

    _REQUEST_FIELDS = {
        'order_id',
        'delivery_picking_id',
        'line_ids',
        'reason',
        'requested_by',
    }
    _WORKFLOW_FIELDS = {
        'state',
        'approver_id',
        'return_picking_id',
        'credit_note_id',
        'name',
        'refund_confirmed',
        'refund_confirmed_by',
        'refund_confirmed_at',
    }

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('state', 'draft') != 'draft':
                raise UserError(_('Yêu cầu trả hàng mới phải ở trạng thái nháp.'))
            if any(
                vals.get(field)
                for field in (
                    'approver_id',
                    'return_picking_id',
                    'credit_note_id',
                    'refund_confirmed',
                    'refund_confirmed_by',
                    'refund_confirmed_at',
                )
            ) or vals.get('name', '/') not in ('/', False):
                raise UserError(
                    _('Không thể tự thiết lập trường trạng thái xử lý yêu cầu.')
                )
            if vals.get('name') in (None, False, '/'):
                vals['name'] = (
                    self.env['ir.sequence'].next_by_code('spa.return.request')
                    or '/'
                )
            vals['requested_by'] = self.env.user.id
        return super().create(vals_list)

    def write(self, vals):
        vals = dict(vals)
        if self._WORKFLOW_FIELDS.intersection(vals):
            raise UserError(_('Vui lòng dùng nút thao tác để đổi trạng thái yêu cầu.'))
        if self._REQUEST_FIELDS.intersection(vals) and any(
            request.state != 'draft' for request in self
        ):
            raise UserError(
                _('Không thể sửa nội dung sau khi gửi yêu cầu trả hàng.')
            )
        if self._REQUEST_FIELDS.intersection(vals) and any(
            request.requested_by != self.env.user
            and not request._is_manager()
            for request in self
        ):
            raise AccessError(
                _('Chỉ người yêu cầu hoặc quản lý Spa mới được sửa yêu cầu.')
            )
        if 'invoice_id' in vals:
            if not self.env.user.has_group('account.group_account_invoice'):
                raise AccessError(
                    _('Bạn cần quyền Kế toán hóa đơn để chọn hóa đơn hoàn.')
                )
            for request in self:
                if (
                    request.state not in ('approved',)
                    or request.credit_note_id
                    or not request.return_received
                ):
                    raise UserError(
                        _('Chỉ được chọn hóa đơn sau khi kho đã nhận hàng trả.')
                    )
        return super().write(vals)

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        if 'line_ids' not in fields_list or values.get('line_ids'):
            return values

        order_id = values.get('order_id')
        if not order_id:
            return values
        order = self.env['sale.order'].browse(order_id).exists()
        if not order:
            return values

        pickings = order._get_spa_returnable_pickings()
        delivery_id = values.get('delivery_picking_id')
        delivery = pickings.filtered(lambda picking: picking.id == delivery_id)
        if not delivery and len(pickings) == 1:
            delivery = pickings
        if not delivery:
            return values

        if 'delivery_picking_id' in fields_list:
            values['delivery_picking_id'] = delivery.id
        values['line_ids'] = self._prepare_return_line_commands(delivery)
        return values

    @api.constrains('order_id', 'invoice_id')
    def _check_invoice(self):
        for request in self.filtered('invoice_id'):
            if (
                request.invoice_id not in request.sudo().order_id.invoice_ids
                or request.invoice_id.move_type != 'out_invoice'
                or request.invoice_id.state != 'posted'
            ):
                raise ValidationError(
                    _('Hóa đơn phải là hóa đơn khách hàng đã ghi sổ của đơn hàng.')
                )

    @api.constrains('order_id', 'delivery_picking_id')
    def _check_delivery_picking(self):
        for request in self:
            picking = request.delivery_picking_id
            if not picking:
                if request.state != 'draft' or any(
                    line.move_id for line in request.line_ids
                ):
                    raise ValidationError(
                        _('Chỉ yêu cầu nháp mới được lưu khi chưa có phiếu xuất kho.')
                    )
                continue
            if (
                (
                    picking.sale_id != request.order_id
                    and not request.order_id._is_spa_invoice_stock_picking(
                        picking
                    )
                )
                or picking.state != 'done'
                or picking.picking_type_code != 'outgoing'
            ):
                raise ValidationError(
                    _('Phiếu xuất kho phải thuộc đơn bán hàng và đã hoàn tất.')
                )
            ordered_products = request.order_id.order_line.mapped(
                'product_id'
            )
            if any(
                line.product_choice_id not in ordered_products
                or (
                    line.move_id
                    and line.move_id.picking_id != picking
                )
                for line in request.line_ids
            ):
                raise ValidationError(
                    _('Sản phẩm trả phải thuộc đơn hàng và phiếu giao đã chọn.')
                )

    @api.onchange('order_id')
    def _onchange_order_id(self):
        for request in self:
            request.line_ids = [(5, 0, 0)]
            pickings = (
                request.order_id._get_spa_returnable_pickings()
                if request.order_id
                else self.env['stock.picking']
            )
            request.delivery_picking_id = (
                pickings[:1] if len(pickings) == 1 else False
            )
            request._onchange_delivery_picking_id()

    @api.onchange('delivery_picking_id')
    def _onchange_delivery_picking_id(self):
        for request in self:
            if not request.delivery_picking_id:
                for line in request.line_ids:
                    line.move_id = False
                continue
            if request.line_ids:
                for line in request.line_ids:
                    move = line._find_move_for_product(
                        request,
                        line.product_choice_id,
                        line,
                    )
                    line.move_id = move
                    if move and line.quantity <= 0:
                        line.quantity = request._available_return_quantity(
                            move
                        )
                continue
            request.line_ids = [
                (5, 0, 0),
                *request._prepare_return_line_commands(
                    request.delivery_picking_id
                ),
            ]

    def _prepare_return_line_commands(self, picking):
        lines = []
        order_products = self.order_id.order_line.mapped('product_id')
        for move in picking.move_ids.filtered(
            lambda item: (
                item.state == 'done'
                and not item.scrapped
                and item.product_id.is_storable
                and item.product_id in order_products
            )
        ):
            available = self._available_return_quantity(move)
            if float_compare(
                available,
                0.0,
                precision_rounding=move.product_id.uom_id.rounding,
            ) > 0:
                lines.append((0, 0, {
                    'move_id': move.id,
                    'product_choice_id': move.product_id.id,
                    'quantity': available,
                }))
        return lines

    @api.depends(
        'line_ids.product_choice_id.display_name',
        'line_ids.quantity',
        'line_ids.product_choice_id.uom_id',
    )
    def _compute_return_line_summaries(self):
        for request in self:
            request.return_product_summary = ', '.join(
                    request.line_ids.mapped('product_choice_id.display_name')
            )
            request.return_quantity_summary = ', '.join(
                    '%s %s' % (
                        line.quantity,
                        line.product_choice_id.uom_id.display_name,
                    )
                    for line in request.line_ids
            )

    def _available_return_quantity(self, move):
        product_uom = move.product_id.uom_id
        delivered = move.product_uom._compute_quantity(
            move.quantity, product_uom
        )
        returned = 0.0
        for returned_move in move.returned_move_ids.filtered(
            lambda item: item.state != 'cancel'
        ):
            quantity = (
                returned_move.quantity
                if returned_move.state == 'done'
                else returned_move.product_uom_qty
            )
            returned += returned_move.product_uom._compute_quantity(
                quantity, product_uom
            )
        pending_requests = self.env['spa.return.request.line'].search([
            ('move_id', '=', move.id),
            ('request_id.state', '=', 'submitted'),
            ('request_id', 'not in', self.ids or [0]),
        ])
        pending = sum(pending_requests.mapped('quantity'))
        return max(delivered - returned - pending, 0.0)

    def _is_manager(self):
        return (
            self.env.user.has_group('spa.group_customer_management_manager')
            or self.env.user.has_group('hr.group_hr_manager')
        )

    @api.depends(
        'return_picking_id',
        'return_picking_id.state',
    )
    def _compute_return_state(self):
        for request in self:
            request.return_state = (
                request.return_picking_id.state
                if request.return_picking_id
                else 'not_created'
            )

    @api.depends(
        'return_picking_id.state',
        'return_picking_id.backorder_ids.state',
        'return_picking_id.move_ids.state',
        'return_picking_id.move_ids.quantity',
        'return_picking_id.backorder_ids.move_ids.state',
        'return_picking_id.backorder_ids.move_ids.quantity',
    )
    def _compute_return_received(self):
        for request in self:
            request.return_received = request._is_return_fully_received()

    @api.depends(
        'credit_note_id.state',
        'credit_note_id.move_type',
        'credit_note_id.amount_residual',
        'credit_note_id.currency_id',
    )
    def _compute_can_register_refund_payment(self):
        for request in self:
            credit_note = request.credit_note_id
            request.can_register_refund_payment = bool(
                credit_note
                and credit_note.move_type == 'out_refund'
                and credit_note.state == 'posted'
                and not credit_note.currency_id.is_zero(
                    credit_note.amount_residual
                )
            )

    @api.depends(
        'order_id',
        'order_id.invoice_ids.state',
        'order_id.invoice_ids.invoice_line_ids.product_id',
        'order_id.invoice_ids.invoice_line_ids.sale_line_ids',
        'order_id.picking_ids.state',
        'order_id.picking_ids.picking_type_code',
        'order_id.picking_ids.move_ids.state',
        'order_id.picking_ids.move_ids.quantity',
        'order_id.picking_ids.move_ids.returned_move_ids.state',
        'order_id.picking_ids.move_ids.returned_move_ids.quantity',
        'order_id.spa_return_request_ids.state',
        'order_id.spa_return_request_ids.line_ids.quantity',
        'order_id.spa_return_request_ids.return_picking_id.state',
    )
    def _compute_returnable_picking_selection(self):
        for request in self:
            pickings = (
                request.order_id._get_spa_returnable_pickings()
                if request.order_id
                else self.env['stock.picking']
            )
            request.needs_delivery_selection = bool(
                request.order_id
                and (
                    not request.delivery_picking_id
                    or len(pickings) != 1
                )
            )

    @api.depends(
        'order_id',
        'order_id.invoice_ids.state',
        'order_id.invoice_ids.invoice_line_ids.product_id',
        'order_id.invoice_ids.invoice_line_ids.sale_line_ids',
        'order_id.picking_ids.state',
    )
    def _compute_returnable_picking_ids(self):
        for request in self:
            request.returnable_picking_ids = (
                request.order_id._get_spa_returnable_pickings()
                if request.order_id
                else self.env['stock.picking']
            )

    @api.depends(
        'order_id',
        'order_id.order_line.product_id',
    )
    def _compute_order_product_ids(self):
        for request in self:
            request.order_product_ids = request.order_id.order_line.mapped(
                'product_id'
            ).filtered('is_storable')

    @api.depends(
        'order_id.invoice_ids.state',
        'order_id.invoice_ids.move_type',
        'invoice_id',
        'credit_note_id',
        'state',
        'return_received',
    )
    def _compute_needs_invoice_selection(self):
        for request in self:
            invoices = request.order_id.invoice_ids.filtered(
                lambda move: (
                    move.move_type == 'out_invoice'
                    and move.state == 'posted'
                )
            )
            request.needs_invoice_selection = bool(
                request.state == 'approved'
                and request.return_received
                and not request.credit_note_id
                and not request.invoice_id
                and len(invoices) > 1
            )

    def _is_return_fully_received(self):
        self.ensure_one()
        if not self.return_picking_id:
            return False
        return_pickings = self._get_return_pickings()
        for line in self.line_ids:
            received = 0.0
            for move in return_pickings.move_ids.filtered(
                lambda item: (
                    item.state == 'done'
                    and item.origin_returned_move_id == line.move_id
                )
            ):
                received += move.product_uom._compute_quantity(
                    move.quantity, line.product_id.uom_id
                )
            if float_compare(
                received,
                line.quantity,
                precision_rounding=line.product_id.uom_id.rounding,
            ) < 0:
                return False
        return bool(self.line_ids)

    def _get_return_pickings(self):
        self.ensure_one()
        root_picking = self.return_picking_id.sudo()
        pickings = root_picking
        pending = root_picking
        while pending:
            next_pickings = pending.backorder_ids - pickings
            pickings |= next_pickings
            pending = next_pickings
        return pickings

    def action_submit(self):
        for request in self:
            if request.state != 'draft':
                raise UserError(_('Chỉ có thể gửi yêu cầu đang ở trạng thái nháp.'))
            if (
                request.requested_by != self.env.user
                and not request._is_manager()
            ):
                raise AccessError(
                    _('Chỉ người yêu cầu hoặc quản lý Spa mới được gửi yêu cầu.')
                )
            if not request.reason or not request.reason.strip():
                raise UserError(_('Vui lòng nhập lý do trả hàng.'))
            if not request.line_ids:
                raise UserError(_('Chọn ít nhất một sản phẩm và số lượng cần trả.'))
            if not request.delivery_picking_id:
                raise UserError(
                    _(
                        'Đơn hàng chưa có phiếu xuất kho hoàn tất. '
                        'Chỉ có thể gửi yêu cầu trả sau khi sản phẩm đã được xuất kho.'
                    )
                )
            if any(not line.move_id for line in request.line_ids):
                raise UserError(
                    _(
                        'Sản phẩm đã chọn chưa có trong phiếu xuất kho '
                        'hoặc không còn số lượng có thể trả.'
                    )
                )
            request._check_requested_quantities()
            request._transition_state('submitted')

    def action_approve(self):
        if not self._is_manager():
            raise AccessError(_('Chỉ quản lý Spa mới được duyệt yêu cầu trả hàng.'))
        self.ensure_one()
        if self.state != 'submitted':
            raise UserError(_('Chỉ có thể duyệt yêu cầu đang chờ duyệt.'))
        request_sudo = self.sudo()
        request_sudo._check_requested_quantities()
        self._transition_state(
            'approved',
            {'approver_id': self.env.user.id},
        )

        wizard = self.env['stock.return.picking'].sudo().with_context(
            active_model='stock.picking',
            active_id=request_sudo.delivery_picking_id.id,
            active_ids=request_sudo.delivery_picking_id.ids,
            spa_return_request_id=self.id,
        ).create({})
        requested_quantities = {
            line.move_id.id: line.quantity for line in request_sudo.line_ids
        }
        for wizard_line in wizard.product_return_moves:
            wizard_line.quantity = requested_quantities.get(
                wizard_line.move_id.id, 0.0
            )
        result = wizard.action_create_returns()
        return_picking = self.env['stock.picking'].browse(result['res_id'])
        super(SpaReturnRequest, self).write({
            'return_picking_id': return_picking.id,
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Yêu cầu trả hàng'),
            'res_model': 'spa.return.request',
            'view_mode': 'form',
            'res_id': self.id,
        }

    def action_refuse(self):
        if not self._is_manager():
            raise AccessError(_('Chỉ quản lý Spa mới được từ chối yêu cầu trả hàng.'))
        for request in self:
            if request.state != 'submitted':
                raise UserError(_('Chỉ có thể từ chối yêu cầu đang chờ duyệt.'))
            request._transition_state(
                'refused',
                {'approver_id': self.env.user.id},
            )

    def action_cancel(self):
        for request in self:
            if request.state not in ('draft', 'submitted'):
                raise UserError(
                    _('Chỉ có thể hủy yêu cầu nháp hoặc đang chờ duyệt.')
                )
            if (
                request.requested_by != self.env.user
                and not request._is_manager()
            ):
                raise AccessError(
                    _('Chỉ người yêu cầu hoặc quản lý Spa mới được hủy yêu cầu.')
                )
            request._transition_state('cancelled')

    def _transition_state(self, state, extra_vals=None):
        transitions = {
            'draft': {'submitted', 'cancelled'},
            'submitted': {'approved', 'refused', 'cancelled'},
        }
        for request in self:
            if state not in transitions.get(request.state, set()):
                raise UserError(
                    _('Không thể chuyển yêu cầu từ trạng thái %(old)s sang %(new)s.',
                      old=request.state, new=state)
                )
        if state in ('approved', 'refused') and not self._is_manager():
            raise AccessError(_('Chỉ quản lý Spa mới được duyệt yêu cầu trả hàng.'))
        vals = {'state': state}
        if extra_vals:
            vals.update(extra_vals)
        return super(SpaReturnRequest, self).write(vals)

    def _link_credit_note(self, credit_note):
        self.ensure_one()
        return super(SpaReturnRequest, self).write({
            'credit_note_id': credit_note.id,
        })

    def _clear_credit_note(self, credit_note):
        self.ensure_one()
        if self.credit_note_id == credit_note:
            return super(SpaReturnRequest, self).write({
                'credit_note_id': False,
            })

    def _set_invoice(self, invoice):
        self.ensure_one()
        return super(SpaReturnRequest, self).write({
            'invoice_id': invoice.id,
        })

    def _check_requested_quantities(self):
        self.ensure_one()
        requested_quantities = {}
        for line in self.line_ids:
            requested_quantities[line.move_id.id] = (
                requested_quantities.get(line.move_id.id, 0.0)
                + line.quantity
            )
        for move_id, quantity in requested_quantities.items():
            move = self.env['stock.move'].browse(move_id)
            available = self._available_return_quantity(move)
            if float_compare(
                quantity,
                0.0,
                precision_rounding=move.product_id.uom_id.rounding,
            ) <= 0 or float_compare(
                quantity,
                available,
                precision_rounding=move.product_id.uom_id.rounding,
            ) > 0:
                raise UserError(
                    _(
                        'Số lượng trả của %(product)s vượt quá số lượng còn có '
                        'thể trả (%(available)s).',
                        product=move.product_id.display_name,
                        available=available,
                    )
                )

    def action_open_return_picking(self):
        self.ensure_one()
        if not self.return_picking_id:
            raise UserError(_('Yêu cầu chưa được duyệt tạo phiếu nhập trả.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Phiếu nhập hàng trả'),
            'res_model': 'stock.picking',
            'view_mode': 'form',
            'res_id': self.return_picking_id.id,
        }

    def action_create_refund(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(_('Bạn cần quyền Kế toán hóa đơn để tạo credit note.'))
        if (
            self.state != 'approved'
            or not self.return_picking_id
            or not self.return_received
        ):
            raise UserError(
                _('Chỉ có thể tạo credit note sau khi kho đã nhận hàng trả.')
            )
        if self.credit_note_id:
            raise UserError(_('Yêu cầu này đã có credit note.'))
        if not self.invoice_id:
            invoices = self.sudo().order_id.invoice_ids.filtered(
                lambda move: (
                    move.move_type == 'out_invoice' and move.state == 'posted'
                )
            )
            if len(invoices) != 1:
                raise UserError(
                    _('Vui lòng chọn hóa đơn khách hàng đã ghi sổ cần hoàn.')
                )
            self._set_invoice(invoices)
        if (
            self.invoice_id not in self.sudo().order_id.invoice_ids
            or self.invoice_id.move_type != 'out_invoice'
            or self.invoice_id.state != 'posted'
        ):
            raise UserError(
                _('Hóa đơn phải là hóa đơn khách hàng đã ghi sổ của đơn hàng này.')
            )
        action = self.invoice_id.action_reverse()
        action['context'] = dict(
            self.env.context,
            active_model='account.move',
            active_id=self.invoice_id.id,
            active_ids=self.invoice_id.ids,
            default_reason=self.reason,
            default_spa_return_request_id=self.id,
        )
        return action

    def action_register_refund_payment(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(
                _('Bạn cần quyền Kế toán hóa đơn để đăng ký thanh toán hoàn.')
            )
        if (
            self.state != 'approved'
            or not self.return_received
            or not self.can_register_refund_payment
        ):
            raise UserError(
                _(
                    'Chỉ có thể đăng ký thanh toán cho credit note đã ghi sổ '
                    'còn số dư cần hoàn.'
                )
            )
        return self.credit_note_id.action_register_payment()

    def action_confirm_refund_paid(self):
        self.ensure_one()
        if not self.env.user.has_group('account.group_account_invoice'):
            raise AccessError(
                _('Bạn cần quyền Kế toán hóa đơn để xác nhận đã hoàn tiền.')
            )
        credit_note = self.credit_note_id
        if (
            self.state != 'approved'
            or not self.return_received
            or not credit_note
            or credit_note.move_type != 'out_refund'
            or credit_note.state != 'posted'
        ):
            raise UserError(
                _(
                    'Chỉ xác nhận hoàn tiền sau khi kho đã nhận hàng và '
                    'credit note đã ghi sổ.'
                )
            )
        if self.refund_confirmed:
            raise UserError(_('Yêu cầu này đã được xác nhận hoàn tiền.'))
        return super(SpaReturnRequest, self).write({
            'refund_confirmed': True,
            'refund_confirmed_by': self.env.user.id,
            'refund_confirmed_at': fields.Datetime.now(),
        })


class SpaReturnRequestLine(models.Model):
    _name = 'spa.return.request.line'
    _description = 'Sản phẩm trong yêu cầu trả hàng'
    _sql_constraints = [
        (
            'spa_return_request_move_unique',
            'unique(request_id, move_id)',
            'Mỗi dòng giao hàng chỉ được xuất hiện một lần trong yêu cầu.',
        ),
    ]

    request_id = fields.Many2one(
        'spa.return.request',
        string='Yêu cầu trả hàng',
        required=True,
        ondelete='cascade',
    )
    move_id = fields.Many2one(
        'stock.move',
        string='Dòng giao hàng',
        ondelete='restrict',
    )
    product_id = fields.Many2one(
        related='move_id.product_id',
        string='Sản phẩm',
        readonly=True,
    )
    product_choice_id = fields.Many2one(
        'product.product',
        string='Sản phẩm trả',
        required=True,
    )
    quantity = fields.Float(
        string='Số lượng trả',
        required=True,
        digits='Product Unit of Measure',
    )
    uom_id = fields.Many2one(
        related='move_id.product_id.uom_id',
        string='Đơn vị',
        readonly=True,
    )

    def _find_move_for_product(self, request, product, line=None):
        if not request or not request.order_id:
            return self.env['stock.move']
        ordered_products = request.order_id.order_line.mapped('product_id')
        if product not in ordered_products:
            raise ValidationError(
                _('Sản phẩm trả phải thuộc đơn bán hàng đã chọn.')
            )
        if not request.delivery_picking_id:
            return self.env['stock.move']

        used_moves = request.line_ids.filtered(
            lambda existing: existing != line
        ).mapped('move_id')
        moves = request.delivery_picking_id.move_ids.filtered(
            lambda move: (
                move.product_id == product
                and move.state == 'done'
                and not move.scrapped
                and move.product_id.is_storable
                and move not in used_moves
            )
        ).filtered(
            lambda move: float_compare(
                request._available_return_quantity(move),
                0.0,
                precision_rounding=move.product_id.uom_id.rounding,
            ) > 0
        )
        if not moves:
            return moves
        return moves.sorted(
            key=lambda move: (
                -request._available_return_quantity(move),
                move.id,
            )
        )[:1]

    @api.onchange('product_choice_id')
    def _onchange_product_choice_id(self):
        for line in self:
            if not line.product_choice_id:
                line.move_id = False
                continue
            line.move_id = line._find_move_for_product(
                line.request_id,
                line.product_choice_id,
                line,
            )
            if line.move_id:
                line.quantity = line.request_id._available_return_quantity(
                    line.move_id
                )

    @api.onchange('move_id')
    def _onchange_move_id(self):
        for line in self:
            if line.move_id:
                line.product_choice_id = line.move_id.product_id
            if line.move_id and line.request_id:
                line.quantity = line.request_id._available_return_quantity(
                    line.move_id
                )

    @api.model_create_multi
    def create(self, vals_list):
        request_ids = {
            vals.get('request_id')
            for vals in vals_list
            if vals.get('request_id')
        }
        if self.env['spa.return.request'].browse(list(request_ids)).filtered(
            lambda request: request.state != 'draft'
        ):
            raise UserError(
                _('Không thể thêm sản phẩm sau khi gửi yêu cầu trả hàng.')
            )
        if self.env['spa.return.request'].browse(list(request_ids)).filtered(
            lambda request: (
                request.requested_by != self.env.user
                and not request._is_manager()
            )
        ):
            raise AccessError(
                _('Chỉ người yêu cầu hoặc quản lý Spa mới được thêm sản phẩm trả.')
            )
        for vals in vals_list:
            request = self.env['spa.return.request'].browse(
                vals.get('request_id')
            )
            if vals.get('move_id'):
                move = self.env['stock.move'].browse(vals['move_id'])
                if (
                    vals.get('product_choice_id')
                    and vals['product_choice_id'] != move.product_id.id
                ):
                    raise ValidationError(
                        _('Sản phẩm trả không khớp dòng giao hàng.')
                    )
                vals['product_choice_id'] = move.product_id.id
            elif vals.get('product_choice_id') and request.delivery_picking_id:
                move = self._find_move_for_product(
                    request,
                    self.env['product.product'].browse(
                        vals['product_choice_id']
                    ),
                )
                if move:
                    vals['move_id'] = move.id
        return super().create(vals_list)

    def write(self, vals):
        if self.filtered(lambda line: line.request_id.state != 'draft'):
            raise UserError(
                _('Không thể sửa sản phẩm sau khi gửi yêu cầu trả hàng.')
            )
        if self.filtered(
            lambda line: (
                line.request_id.requested_by != self.env.user
                and not line.request_id._is_manager()
            )
        ):
            raise AccessError(
                _('Chỉ người yêu cầu hoặc quản lý Spa mới được sửa sản phẩm trả.')
            )
        if 'product_choice_id' in vals:
            for line in self:
                if not vals['product_choice_id']:
                    raise ValidationError(_('Vui lòng chọn sản phẩm trả.'))
                line_vals = dict(vals)
                move = self._find_move_for_product(
                    line.request_id,
                    self.env['product.product'].browse(
                        vals['product_choice_id']
                    ),
                    line,
                )
                line_vals['move_id'] = move.id if move else False
                super(SpaReturnRequestLine, line).write(line_vals)
            return True
        if vals.get('move_id'):
            vals = dict(vals)
            vals['product_choice_id'] = (
                self.env['stock.move'].browse(vals['move_id']).product_id.id
            )
        return super().write(vals)

    def unlink(self):
        if self.filtered(lambda line: line.request_id.state != 'draft'):
            raise UserError(
                _('Không thể xóa sản phẩm sau khi gửi yêu cầu trả hàng.')
            )
        if self.filtered(
            lambda line: (
                line.request_id.requested_by != self.env.user
                and not line.request_id._is_manager()
            )
        ):
            raise AccessError(
                _('Chỉ người yêu cầu hoặc quản lý Spa mới được sửa sản phẩm trả.')
            )
        return super().unlink()

    @api.constrains(
        'request_id',
        'move_id',
        'product_choice_id',
        'quantity',
    )
    def _check_line(self):
        for line in self:
            if (
                line.product_choice_id
                not in line.request_id.order_id.order_line.mapped('product_id')
                or not line.product_choice_id.is_storable
            ):
                raise ValidationError(
                    _('Sản phẩm trả phải là hàng lưu kho thuộc đơn hàng.')
                )
            if not line.move_id:
                if line.request_id.state != 'draft':
                    raise ValidationError(
                        _('Cần chọn phiếu xuất kho trước khi gửi yêu cầu.')
                    )
            elif (
                line.move_id.picking_id != line.request_id.delivery_picking_id
                or line.move_id.state != 'done'
                or not line.move_id.product_id.is_storable
                or line.move_id.product_id != line.product_choice_id
            ):
                raise ValidationError(
                    _(
                        'Sản phẩm trả phải có trong phiếu xuất kho '
                        'đã hoàn tất đã chọn.'
                    )
                )
            if float_compare(
                line.quantity,
                0.0,
                precision_rounding=line.product_choice_id.uom_id.rounding,
            ) <= 0:
                raise ValidationError(_('Số lượng trả phải lớn hơn 0.'))


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def action_create_returns(self):
        for wizard in self:
            picking = wizard.picking_id
            if (
                picking.picking_type_code == 'outgoing'
                and (
                    picking.sale_id
                    or self.env.context.get('spa_return_request_id')
                )
            ):
                request_id = self.env.context.get('spa_return_request_id')
                request = self.env['spa.return.request'].browse(
                    request_id
                ).exists()
                if (
                    not request
                    or request.state != 'approved'
                    or request.delivery_picking_id != picking
                    or request.return_picking_id
                ):
                    raise UserError(
                        _(
                            'Cần có yêu cầu trả hàng được quản lý Spa duyệt '
                            'trước khi tạo phiếu nhập trả.'
                        )
                    )
                request_quantities = {
                    line.move_id.id: line.quantity for line in request.line_ids
                }
                for wizard_line in wizard.product_return_moves:
                    expected = request_quantities.get(
                        wizard_line.move_id.id, 0.0
                    )
                    if float_compare(
                        wizard_line.quantity,
                        expected,
                        precision_rounding=wizard_line.uom_id.rounding,
                    ):
                        raise UserError(
                            _('Số lượng trên phiếu trả phải khớp yêu cầu đã duyệt.')
                        )
        return super().action_create_returns()


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def button_validate(self):
        source_pickings = self.move_ids.origin_returned_move_id.picking_id
        requests = self.env['spa.return.request'].search([
            ('state', '=', 'approved'),
            ('delivery_picking_id', 'in', source_pickings.ids),
        ]).filtered(
            lambda request: bool(
                (request.return_picking_id
                 | request.return_picking_id.backorder_ids) & self
            )
        )
        for request in requests:
            allowed_quantities = {
                line.move_id.id: line.quantity for line in request.line_ids
            }
            returned_quantities = {}
            return_pickings = request._get_return_pickings()
            for move in return_pickings.move_ids.filtered(
                lambda item: item.state != 'cancel'
            ):
                original_move = move.origin_returned_move_id
                if not original_move:
                    continue
                quantity = (
                    move.quantity
                    if move.picking_id in self or move.state == 'done'
                    else move.product_uom_qty
                )
                quantity = move.product_uom._compute_quantity(
                    quantity, move.product_id.uom_id
                )
                returned_quantities[original_move.id] = (
                    returned_quantities.get(original_move.id, 0.0) + quantity
                )
            for move_id, quantity in returned_quantities.items():
                if float_compare(
                    quantity,
                    allowed_quantities.get(move_id, 0.0),
                    precision_rounding=(
                        request.line_ids.filtered(
                            lambda line: line.move_id.id == move_id
                        ).product_id.uom_id.rounding
                    ),
                ) > 0:
                    raise UserError(
                        _(
                            'Số lượng nhận trả không được vượt quá số lượng '
                            'đã duyệt cho %(product)s.',
                            product=request.line_ids.filtered(
                                lambda line: line.move_id.id == move_id
                            ).product_id.display_name,
                        )
                    )
        return super().button_validate()


class AccountMoveReversal(models.TransientModel):
    _inherit = 'account.move.reversal'

    spa_return_request_id = fields.Many2one(
        'spa.return.request',
        string='Yêu cầu trả hàng',
        readonly=True,
    )

    def refund_moves(self):
        for wizard in self.filtered('spa_return_request_id'):
            request = wizard.spa_return_request_id
            if (
                not request
                or request.state != 'approved'
                or not request.return_received
                or request.credit_note_id
                or wizard.move_ids != request.invoice_id
            ):
                raise UserError(
                    _('Không thể tạo credit note nếu yêu cầu chưa đủ điều kiện.')
                )
        result = super().refund_moves()
        for wizard in self.filtered('spa_return_request_id'):
            credit_notes = wizard.new_move_ids.filtered(
                lambda move: move.move_type == 'out_refund'
            )
            if len(credit_notes) != 1:
                raise UserError(
                    _('Yêu cầu trả hàng phải tạo đúng một credit note.')
                )
            request = wizard.spa_return_request_id
            request_sudo = request.sudo()
            remaining_quantities = {}
            return_pickings = request_sudo._get_return_pickings()
            for move in return_pickings.move_ids.filtered(
                lambda item: item.state == 'done'
            ):
                sale_line = move.origin_returned_move_id.sale_line_id
                if not sale_line:
                    continue
                returned_quantity = move.product_uom._compute_quantity(
                    move.quantity, move.product_id.uom_id
                )
                remaining_quantities[sale_line.id] = (
                    remaining_quantities.get(sale_line.id, 0.0)
                    + returned_quantity
                )
            adjusted_lines = credit_notes.invoice_line_ids.filtered(
                lambda line: line.display_type == 'product' and line.product_id
            )
            for line in adjusted_lines:
                available_quantity = sum(
                    remaining_quantities.get(sale_line.id, 0.0)
                    for sale_line in line.sale_line_ids
                    if sale_line.order_id == request_sudo.order_id
                )
                invoice_quantity = line.product_uom_id._compute_quantity(
                    line.quantity, line.product_id.uom_id
                )
                quantity_to_refund = min(
                    available_quantity, invoice_quantity
                )
                line.quantity = line.product_id.uom_id._compute_quantity(
                    quantity_to_refund, line.product_uom_id
                )
                remaining_to_allocate = quantity_to_refund
                for sale_line in line.sale_line_ids.filtered(
                    lambda item: item.order_id == request_sudo.order_id
                ):
                    allocated = min(
                        remaining_quantities.get(sale_line.id, 0.0),
                        remaining_to_allocate,
                    )
                    remaining_quantities[sale_line.id] = (
                        remaining_quantities.get(sale_line.id, 0.0)
                        - allocated
                    )
                    remaining_to_allocate -= allocated
                    if not remaining_to_allocate:
                        break
            if not adjusted_lines.filtered(
                lambda line: line.quantity > 0
            ):
                raise UserError(
                    _('Không tìm thấy dòng hóa đơn tương ứng với hàng đã nhận trả.')
                )
            request_sudo._link_credit_note(credit_notes)
        return result
