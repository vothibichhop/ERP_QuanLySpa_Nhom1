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
        readonly=True,
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
        string='Phiếu giao hàng',
        required=True,
        ondelete='restrict',
        domain="[('sale_id', '=', order_id), ('state', '=', 'done'), "
               "('picking_type_code', '=', 'outgoing')]",
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
        related='return_picking_id.state',
        string='Trạng thái nhận hàng',
    )
    return_received = fields.Boolean(
        string='Đã nhận đủ hàng trả',
        compute='_compute_return_received',
        compute_sudo=True,
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
            if (
                picking.sale_id != request.order_id
                or picking.state != 'done'
                or picking.picking_type_code != 'outgoing'
            ):
                raise ValidationError(
                    _('Phiếu giao hàng phải thuộc đơn bán hàng và đã hoàn tất.')
                )

    @api.onchange('delivery_picking_id')
    def _onchange_delivery_picking_id(self):
        for request in self:
            if not request.delivery_picking_id:
                request.line_ids = [(5, 0, 0)]
                continue
            lines = []
            for move in request.delivery_picking_id.move_ids.filtered(
                lambda item: (
                    item.state == 'done'
                    and not item.scrapped
                    and item.product_id.is_storable
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
                        'quantity': available,
                    }))
            request.line_ids = [(5, 0, 0), *lines]

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
        required=True,
        ondelete='restrict',
    )
    product_id = fields.Many2one(
        related='move_id.product_id',
        string='Sản phẩm',
        readonly=True,
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

    @api.constrains('request_id', 'move_id', 'quantity')
    def _check_line(self):
        for line in self:
            if (
                line.move_id.picking_id != line.request_id.delivery_picking_id
                or line.move_id.state != 'done'
                or not line.move_id.product_id.is_storable
            ):
                raise ValidationError(
                    _('Chỉ được trả sản phẩm đã giao trong phiếu giao hàng đã chọn.')
                )
            if float_compare(
                line.quantity,
                0.0,
                precision_rounding=line.move_id.product_id.uom_id.rounding,
            ) <= 0:
                raise ValidationError(_('Số lượng trả phải lớn hơn 0.'))


class StockReturnPicking(models.TransientModel):
    _inherit = 'stock.return.picking'

    def action_create_returns(self):
        for wizard in self:
            picking = wizard.picking_id
            if (
                picking.picking_type_code == 'outgoing'
                and picking.sale_id
            ):
                request_id = self.env.context.get('spa_return_request_id')
                request = self.env['spa.return.request'].browse(request_id)
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
