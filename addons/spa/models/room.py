from odoo import fields, models


class SpaRoom(models.Model):
    _name = 'spa.room'
    _description = 'Phòng Spa'
    _order = 'name'

    name = fields.Char(string='Tên phòng', required=True)
    active = fields.Boolean(string='Đang hoạt động', default=True)
    bed_ids = fields.One2many('spa.bed', 'room_id', string='Giường')

    _sql_constraints = [
        ('spa_room_name_unique', 'unique(name)', 'Tên phòng không được trùng.'),
    ]
