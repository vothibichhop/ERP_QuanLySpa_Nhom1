from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaLeaveRequest(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên nghỉ phép',
        })
        cls.start_date = fields.Date.today() + timedelta(days=10)

    def _create_leave(self, **values):
        leave_values = {
            'employee_id': self.employee.id,
            'start_date': self.start_date,
            'end_date': self.start_date + timedelta(days=2),
        }
        leave_values.update(values)
        return self.env['spa.leave.request'].create(leave_values)

    def _create_user(self, login, group_xmlid):
        return self.env['res.users'].create({
            'name': login,
            'login': login,
            'groups_id': [(6, 0, [self.env.ref(group_xmlid).id])],
        })

    def test_duration_counts_both_start_and_end_dates(self):
        leave = self._create_leave()

        self.assertEqual(leave.duration_days, 3)
        self.assertEqual(leave.total_sessions, 6)

    def test_partial_sessions_are_counted(self):
        leave = self._create_leave(
            start_session='afternoon',
            end_session='morning',
        )

        self.assertEqual(leave.total_sessions, 4)

    def test_same_day_leave_can_cover_one_or_two_sessions(self):
        morning_leave = self._create_leave(
            end_date=self.start_date,
            end_session='morning',
        )
        afternoon_leave = self._create_leave(
            start_date=self.start_date + timedelta(days=1),
            end_date=self.start_date + timedelta(days=1),
            start_session='afternoon',
            end_session='afternoon',
        )

        self.assertEqual(morning_leave.total_sessions, 1)
        self.assertEqual(afternoon_leave.total_sessions, 1)

    def test_same_day_end_session_cannot_precede_start_session(self):
        with self.assertRaises(ValidationError):
            self._create_leave(
                end_date=self.start_date,
                start_session='afternoon',
                end_session='morning',
            )

    def test_leave_rejects_end_date_before_start_date(self):
        with self.assertRaises(ValidationError):
            self._create_leave(end_date=self.start_date - timedelta(days=1))

    def test_submitted_leave_cannot_overlap_another_active_request(self):
        first_leave = self._create_leave()
        first_leave.action_submit()

        with self.assertRaises(ValidationError):
            overlapping_leave = self._create_leave(
                start_date=first_leave.end_date,
                end_date=first_leave.end_date + timedelta(days=1),
            )
            overlapping_leave.action_submit()

    def test_non_overlapping_sessions_on_the_same_day_can_be_submitted(self):
        morning_leave = self._create_leave(
            end_date=self.start_date,
            end_session='morning',
        )
        morning_leave.action_submit()
        afternoon_leave = self._create_leave(
            start_date=self.start_date,
            end_date=self.start_date,
            start_session='afternoon',
            end_session='afternoon',
        )

        afternoon_leave.action_submit()

        self.assertEqual(afternoon_leave.state, 'submitted')

    def test_draft_leave_does_not_block_a_submitted_request(self):
        self._create_leave()

        submitted_leave = self._create_leave()
        submitted_leave.action_submit()

        self.assertEqual(submitted_leave.state, 'submitted')

    def test_new_leave_must_start_as_a_draft(self):
        with self.assertRaises(UserError):
            self._create_leave(state='approved')

    def test_submitted_leave_details_cannot_be_changed(self):
        leave = self._create_leave()
        leave.action_submit()

        with self.assertRaises(UserError):
            leave.write({'start_date': leave.start_date + timedelta(days=1)})

        self.assertEqual(leave.start_date, self.start_date)

    def test_only_managers_can_approve_or_refuse_requests(self):
        leave = self._create_leave()
        leave.action_submit()
        regular_user = self._create_user(
            'spa_leave_user',
            'spa.group_customer_management_user',
        )

        with self.assertRaises(AccessError):
            leave.with_user(regular_user).action_approve()

        manager = self._create_user(
            'spa_leave_manager',
            'spa.group_customer_management_manager',
        )
        leave.with_user(manager).action_approve()

        self.assertEqual(leave.state, 'approved')
        self.assertEqual(leave.approver_id, manager)

    def test_refusal_records_the_reviewer(self):
        leave = self._create_leave()
        leave.action_submit()
        manager = self._create_user(
            'spa_leave_refusing_manager',
            'spa.group_customer_management_manager',
        )

        leave.with_user(manager).action_refuse()

        self.assertEqual(leave.state, 'refused')
        self.assertEqual(leave.approver_id, manager)

    def test_hr_managers_can_approve_and_cancel_approved_requests(self):
        manager = self._create_user(
            'spa_leave_hr_manager',
            'spa.group_customer_management_user',
        )
        manager.groups_id = [
            (4, self.env.ref('hr.group_hr_manager').id),
        ]
        leave = self._create_leave()
        leave.action_submit()

        leave.with_user(manager).action_approve()
        self.assertEqual(leave.state, 'approved')
        self.assertEqual(leave.approver_id, manager)

        leave.with_user(manager).action_cancel()
        self.assertEqual(leave.state, 'cancelled')

    def test_invalid_state_transitions_are_rejected(self):
        leave = self._create_leave()

        with self.assertRaises(UserError):
            leave.action_approve()

        self.assertEqual(leave.state, 'draft')
