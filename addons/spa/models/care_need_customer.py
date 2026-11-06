from odoo import models, fields

class CustomerCareNeed(models.Model):
    _name = 'customer.care.need'
    _description = 'Nhu cầu chăm sóc khách hàng'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc, id desc'

    name = fields.Char(string='Tên nhu cầu', required=True, tracking=True)
    partner_id = fields.Many2one(
        'res.partner', string='Khách hàng', required=True, index=True, ondelete='restrict'
    )
    need_type = fields.Selection([
        ('consultation', 'Tư vấn'),
        ('followup', 'Chăm sóc sau dịch vụ'),
        ('promotion', 'Khuyến mãi'),
        ('other', 'Khác'),
    ], string='Loại nhu cầu', required=True, default='consultation')
    description = fields.Text(string='Mô tả nhu cầu')
    state = fields.Selection([
        ('new', 'Mới'),
        ('processing', 'Đang xử lý'),
        ('done', 'Hoàn thành'),
        ('cancel', 'Đã hủy'),
    ], string='Trạng thái', default='new', required=True, tracking=True)
    next_date = fields.Date(string='Ngày chăm sóc tiếp theo')
    user_id = fields.Many2one(
        'res.users', string='Nhân viên phụ trách', default=lambda self: self.env.user
    )

    def action_start(self):
        self.write({'state': 'processing'})

    def action_done(self):
        self.write({'state': 'done'})

    def action_cancel(self):
        self.write({'state': 'cancel'})
