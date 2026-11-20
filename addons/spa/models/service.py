from odoo import fields, models


class SpaService(models.Model):
    _name = 'spa.service'
    _description = 'Dịch vụ Spa'

    name = fields.Char(string='Tên dịch vụ', required=True)
    category = fields.Selection([
        ('massage', 'Massage'),
        ('facial', 'Facial'),
        ('hair', 'Hair'),
        ('spa_package', 'Spa Package'),
    ], string='Danh mục')
    duration_minutes = fields.Integer(string='Thời lượng (phút)', required=True)
    price = fields.Float(string='Giá dịch vụ', required=True)
    description = fields.Text(string='Mô tả')
    active = fields.Boolean(default=True, string='Đang hoạt động')
