from odoo import fields, models


class SpaBed(models.Model):
    _name = 'spa.bed'
    _description = 'Giường Spa'
    _order = 'name'

    name = fields.Char(string='Tên giường', required=True)
    room_id = fields.Many2one(
        'spa.room',
        string='Phòng',
        required=True,
        ondelete='cascade',
    )
    active = fields.Boolean(string='Đang hoạt động', default=True)

    _sql_constraints = [
        ('spa_bed_name_unique', 'unique(name)', 'Tên giường không được trùng.'),
    ]
