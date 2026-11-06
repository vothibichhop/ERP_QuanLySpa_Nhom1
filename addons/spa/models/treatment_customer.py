from odoo import models, fields, api
from odoo.exceptions import ValidationError


class CustomerTreatment(models.Model):
    _name = 'customer.treatment'
    _description = 'Liệu trình khách hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'start_date desc, id desc'

    name = fields.Char(string='Tên liệu trình', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, index=True, ondelete='restrict'
    )
    start_date = fields.Date(string='Ngày bắt đầu')
    end_date = fields.Date(string='Ngày kết thúc')
    state = fields.Selection([
        ('draft', 'Dự kiến'),
        ('in_progress', 'Đang thực hiện'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Đã hủy'),
    ], string='Trạng thái', default='draft', required=True, tracking=True)
    description = fields.Text(string='Mô tả liệu trình')
    note = fields.Text(string='Lưu ý')
    user_id = fields.Many2one(
        'res.users', string='Nhân viên phụ trách', default=lambda self: self.env.user
    )

    @api.constrains('start_date', 'end_date')
    def _check_dates(self):
        for rec in self:
            if rec.start_date and rec.end_date and rec.end_date < rec.start_date:
                raise ValidationError('Ngày kết thúc không được trước ngày bắt đầu.')
