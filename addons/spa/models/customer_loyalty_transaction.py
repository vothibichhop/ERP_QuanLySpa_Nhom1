from odoo import models, fields, api, _
from odoo.exceptions import UserError, ValidationError

class CustomerLoyaltyTransaction(models.Model):
    _name = 'customer.loyalty.transaction'
    _description = 'Giao dịch điểm tích lũy'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nội dung giao dịch', required=True)
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, index=True, ondelete='restrict'
    )
    appointment_id = fields.Many2one(
        'spa.appointment',
        string='Lịch hẹn Spa',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )
    date = fields.Date(string='Ngày giao dịch', default=fields.Date.context_today, required=True)
    transaction_type = fields.Selection([
        ('earn', 'Cộng điểm'),
        ('redeem', 'Sử dụng điểm'),
        ('adjust_add', 'Điều chỉnh tăng'),
        ('adjust_sub', 'Điều chỉnh giảm'),
    ], string='Loại giao dịch', required=True, default='earn')
    points = fields.Integer(string='Số điểm', required=True)
    note = fields.Text(string='Ghi chú')
    state = fields.Selection([
        ('draft', 'Nháp'),
        ('applied', 'Đã áp dụng'),
    ], string='Trạng thái', default='draft', readonly=True, copy=False, required=True)
    applied_by = fields.Many2one('res.users', string='Người áp dụng', readonly=True, copy=False)
    applied_at = fields.Datetime(string='Thời điểm áp dụng', readonly=True, copy=False)

    _sql_constraints = [
        (
            'spa_appointment_loyalty_unique',
            'unique(appointment_id)',
            'Mỗi lịch hẹn Spa chỉ được cộng điểm một lần.',
        ),
    ]

    @api.constrains('points')
    def _check_points_positive(self):
        for rec in self:
            if rec.points <= 0:
                raise ValidationError(_('Số điểm phải lớn hơn 0.'))

    def write(self, vals):
        if any(rec.state == 'applied' for rec in self):
            protected = set(vals) - {'note'}
            if protected:
                raise UserError(_('Không thể sửa giao dịch điểm đã áp dụng. Chỉ được bổ sung ghi chú.'))
        return super().write(vals)

    def unlink(self):
        if any(rec.state == 'applied' for rec in self):
            raise UserError(_('Không thể xóa giao dịch điểm đã áp dụng.'))
        return super().unlink()

    def action_apply_points(self):
        for rec in self:
            if rec.state == 'applied':
                raise UserError(_('Giao dịch này đã được áp dụng trước đó.'))
            if rec.points <= 0:
                raise ValidationError(_('Số điểm phải lớn hơn 0.'))

            # Lock partner row to avoid two concurrent redemptions overspending points.
            self.env.cr.execute(
                'SELECT loyalty_point FROM res_partner WHERE id = %s FOR UPDATE',
                (rec.partner_id.id,)
            )
            row = self.env.cr.fetchone()
            if not row:
                raise UserError(_('Không tìm thấy khách hàng.'))
            current_points = row[0] or 0

            if rec.transaction_type in ('earn', 'adjust_add'):
                new_points = current_points + rec.points
            else:
                if current_points < rec.points:
                    raise UserError(_('Khách hàng không đủ điểm để thực hiện giao dịch này.'))
                new_points = current_points - rec.points

            partner = rec.partner_id.sudo()
            partner.write({
                'loyalty_point': new_points,
                'customer_type': partner._customer_type_for_loyalty_points(
                    new_points
                ),
            })
            partner.env['sale.order'].search([
                ('partner_id', '=', partner.id),
                ('state', 'in', ('draft', 'sent')),
            ])._update_spa_tier_discount()
            rec.write({
                'state': 'applied',
                'applied_by': self.env.user.id,
                'applied_at': fields.Datetime.now(),
            })
        return True
