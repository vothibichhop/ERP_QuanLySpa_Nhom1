from datetime import timedelta

from odoo.exceptions import ValidationError
from odoo.fields import Command
from odoo.tests import TransactionCase, tagged
from odoo.tools.safe_eval import safe_eval


@tagged('post_install', '-at_install')
class TestSpaTreatmentPackages(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.customer = cls.env['res.partner'].create({
            'name': 'Treatment Package Customer',
        })
        cls.service = cls.env['product.template'].create({
            'name': 'Treatment Package Service',
            'type': 'service',
            'list_price': 100.0,
        })
        cls.package = cls.env['spa.treatment.package'].create({
            'name': 'Three Visit Package',
            'price': 250.0,
            'validity_days': 30,
            'line_ids': [Command.create({
                'product_id': cls.service.id,
                'session_count': 3,
            })],
        })

    def _create_customer_package(self):
        return self.env['spa.customer.package'].create({
            'partner_id': self.customer.id,
            'package_id': self.package.id,
        })

    def test_customer_package_copies_session_allowance(self):
        customer_package = self._create_customer_package()
        line = customer_package.line_ids

        self.assertEqual(line.product_id, self.service)
        self.assertEqual(customer_package.session_count, 3)
        self.assertEqual(customer_package.remaining_session_count, 3)
        self.assertEqual(customer_package.price, 250.0)
        self.assertEqual(
            customer_package.expiration_date,
            customer_package.start_date + timedelta(days=29),
        )
        self.assertEqual(customer_package.state, 'active')
        self.package.write({'validity_days': 60, 'price': 300.0})
        self.assertEqual(
            customer_package.expiration_date,
            customer_package.start_date + timedelta(days=29),
        )
        self.assertEqual(customer_package.price, 250.0)

    def test_package_is_a_saleable_product_and_appears_in_catalog(self):
        action = self.env.ref('spa.action_spa_treatment_package_products')

        self.assertTrue(self.package.product_id.sale_ok)
        self.assertEqual(self.package.product_id.type, 'service')
        self.assertEqual(self.package.product_id.list_price, self.package.price)
        self.assertIn(
            'Treatment Package Service: 3 buổi',
            self.package.product_id.spa_treatment_package_service_summary,
        )
        self.assertIn(
            'Treatment Package Service: 3 buổi',
            self.package.product_id.description_sale,
        )
        self.assertEqual(action.res_model, 'spa.treatment.package')
        self.assertIn(action.domain, (False, '[]'))
        self.assertTrue(safe_eval(action.context).get('create'))
        self.assertIn(
            self.package,
            self.env[action.res_model].search(safe_eval(action.domain or '[]')),
        )

    def test_editing_package_services_updates_sales_product_details(self):
        line = self.package.line_ids
        line.session_count = 4

        self.assertIn(
            'Treatment Package Service: 4 buổi',
            self.package.product_id.spa_treatment_package_service_summary,
        )
        self.assertIn(
            'Treatment Package Service: 4 buổi',
            self.package.product_id.description_sale,
        )

    def test_package_accepts_multiple_distinct_services(self):
        second_service = self.env['product.template'].create({
            'name': 'Second Treatment Package Service',
            'type': 'service',
            'list_price': 150.0,
        })
        self.package.write({
            'line_ids': [
                Command.create({
                    'product_id': second_service.id,
                    'session_count': 2,
                }),
            ],
        })

        self.assertEqual(len(self.package.line_ids), 2)
        self.assertEqual(
            set(self.package.line_ids.mapped('product_id').ids),
            {self.service.id, second_service.id},
        )
        self.assertIn(
            'Second Treatment Package Service: 2 buổi',
            self.package.product_id.spa_treatment_package_service_summary,
        )

    def test_package_product_cannot_be_added_as_a_child_service(self):
        with self.assertRaises(ValidationError):
            self.env['spa.treatment.package.line'].create({
                'package_id': self.package.id,
                'product_id': self.package.product_id.id,
                'session_count': 1,
            })

    def test_package_state_tracks_business_status(self):
        self.assertEqual(self.package.state, 'active')
        self.package.state = 'inactive'

        self.assertFalse(self.package.active)
        self.assertEqual(self.package.state, 'inactive')

    def test_initial_treatment_packages_are_saleable_products(self):
        package_xmlids = (
            'treatment_package_facial_basic_5',
            'treatment_package_facial_deep_5',
            'treatment_package_skin_recovery_5',
            'treatment_package_body_massage_5',
            'treatment_package_hair_wellness_5',
            'treatment_package_body_care_5',
        )
        packages = self.env[
            'spa.treatment.package'
        ].browse([
            self.env.ref(f'spa.{xmlid}').id for xmlid in package_xmlids
        ])

        self.assertEqual(len(packages), 6)
        self.assertTrue(all(packages.mapped('product_id.sale_ok')))
        self.assertTrue(all(packages.mapped('product_id')))
        self.assertTrue(all(
            package.product_id.spa_treatment_package_service_summary
            for package in packages
        ))

    def test_confirming_sale_creates_customer_packages(self):
        order = self.env['sale.order'].create({
            'partner_id': self.customer.id,
            'order_line': [Command.create({
                'product_id': self.package.product_id.product_variant_id.id,
                'product_uom_qty': 2,
            })],
        })

        order.action_confirm()

        customer_packages = self.env['spa.customer.package'].search([
            ('sale_order_id', '=', order.id),
        ])
        self.assertEqual(len(customer_packages), 2)
        self.assertTrue(all(
            record.package_id == self.package
            for record in customer_packages
        ))

    def test_completed_sessions_decrease_balance_and_prevent_overuse(self):
        customer_package = self._create_customer_package()
        line = customer_package.line_ids
        session_model = self.env['spa.customer.package.session']

        session_model.create({'package_line_id': line.id})
        self.assertEqual(line.used_session_count, 1)
        self.assertEqual(line.remaining_session_count, 2)

        session_model.create({
            'package_line_id': line.id,
            'state': 'cancelled',
        })
        self.assertEqual(line.used_session_count, 1)

        session_model.create({'package_line_id': line.id})
        session_model.create({'package_line_id': line.id})
        self.assertEqual(customer_package.remaining_session_count, 0)
        self.assertEqual(customer_package.state, 'completed')

        with self.assertRaises(ValidationError):
            session_model.create({'package_line_id': line.id})

    def test_session_outside_validity_period_is_rejected(self):
        customer_package = self._create_customer_package()
        line = customer_package.line_ids

        with self.assertRaises(ValidationError):
            self.env['spa.customer.package.session'].create({
                'package_line_id': line.id,
                'session_date': customer_package.expiration_date
                + timedelta(days=1),
            })
