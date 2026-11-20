from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestCustomerPhone(TransactionCase):

    def test_phone_and_mobile_accept_valid_numbers(self):
        partner = self.env['res.partner'].create({
            'name': 'SPA Valid Phone Customer',
            'phone': '037 442 0176',
            'mobile': '037-442-0176',
        })

        self.assertEqual(partner.phone, '037 442 0176')
        self.assertEqual(partner.mobile, '037-442-0176')

    def test_phone_and_mobile_must_be_valid_vietnamese_numbers(self):
        for field_name in ('phone', 'mobile'):
            with self.subTest(field=field_name):
                with self.assertRaises(ValidationError):
                    self.env['res.partner'].create({
                        'name': 'SPA Invalid Phone Customer',
                        field_name: '1234567890',
                    })

    def test_phone_update_must_be_valid(self):
        partner = self.env['res.partner'].create({
            'name': 'SPA Phone Update Customer',
            'phone': '0374420176',
        })

        with self.assertRaises(ValidationError):
            partner.write({'phone': '037442017'})

    def test_empty_and_duplicate_numbers_are_allowed(self):
        partners = self.env['res.partner'].create([
            {'name': 'SPA Shared Phone Customer 1', 'phone': '0374420176'},
            {'name': 'SPA Shared Phone Customer 2', 'mobile': '0374420176'},
            {'name': 'SPA No Phone Customer'},
        ])

        self.assertEqual(len(partners), 3)
