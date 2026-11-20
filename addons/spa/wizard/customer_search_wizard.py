from odoo import fields, models
from odoo.exceptions import UserError


class SpaCustomerSearchWizard(models.TransientModel):
    _name = 'spa.customer.search.wizard'
    _description = 'Tra cứu khách hàng'

    search_term = fields.Char(
        string='Tên, số điện thoại, email hoặc mã khách hàng',
        required=True,
    )

    def action_search(self):
        self.ensure_one()
        search_term = (self.search_term or '').strip()
        if not search_term:
            raise UserError('Vui lòng nhập thông tin cần tra cứu.')

        return {
            'type': 'ir.actions.act_window',
            'name': 'Kết quả tra cứu khách hàng',
            'res_model': 'res.partner',
            'view_mode': 'list,form',
            'domain': [
                '|', '|', '|', '|', '|',
                ('name', 'ilike', search_term),
                ('phone', 'ilike', search_term),
                ('mobile', 'ilike', search_term),
                ('email', 'ilike', search_term),
                ('customer_code', 'ilike', search_term),
                ('spa_customer_code', 'ilike', search_term),
            ],
            'target': 'current',
        }
