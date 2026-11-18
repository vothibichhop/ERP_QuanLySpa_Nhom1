from datetime import time, timedelta

from odoo import fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestSpaWorkShift(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.employee = cls.env['hr.employee'].create({
            'name': 'Nhân viên ca trực',
        })
        cls.guard = cls.env['hr.employee'].create({
            'name': 'Bảo vệ ca trực',
            'job_id': cls.env.ref('spa.job_spa_security').id,
        })

    def _create_shift(self, **values):
        work_date = fields.Date.context_today(self.env.user)
        shift_values = {
            'name': 'Ca sáng',
            'employee_ids': [(4, self.employee.id)],
            'work_date': work_date,
        }
        shift_values.update(values)
        return self.env['spa.work.shift'].create(shift_values)

    def test_shift_rejects_non_full_day_hours(self):
        work_date = fields.Date.context_today(self.env.user)
        shift = self._create_shift()
        with self.assertRaises(ValidationError):
            shift.write({
                'end_datetime': self.env['spa.work.shift']._shift_datetime(
                    work_date, time(18),
                ),
            })

    def test_employee_cannot_have_overlapping_shifts(self):
        shift = self._create_shift()
        with self.assertRaises(ValidationError):
            self._create_shift(
                name='Ca trùng',
                work_date=shift.work_date,
            )

    def test_employee_cannot_be_scheduled_during_leave(self):
        work_date = fields.Date.context_today(self.env.user)
        leave = self.env['spa.leave.request'].create({
            'employee_id': self.employee.id,
            'start_date': work_date,
            'end_date': work_date,
        })
        leave.action_submit()

        with self.assertRaises(ValidationError):
            self._create_shift()

    def test_cancelled_overlaps_are_allowed(self):
        shift = self._create_shift()
        self._create_shift(
            name='Ca thay thế',
            state='cancelled',
        )

        self.assertEqual(len(self.employee.shift_ids), 2)
        self.assertEqual(shift.shift_type, 'full_day')
        self.assertEqual(shift.work_date, fields.Date.context_today(self.env.user))

    def test_daily_guard_schedule_is_generated_once(self):
        shifts = self.env['spa.work.shift']
        shifts._cron_create_daily_guard_shift()
        shifts._cron_create_daily_guard_shift()

        guard_shift = shifts.search([
            ('auto_generated', '=', True),
            ('work_date', '=', fields.Date.context_today(self.env.user)),
        ])
        expected_guards = self.env['hr.employee'].search([
            ('active', '=', True),
            '|',
            ('job_title', 'ilike', 'bảo vệ'),
            ('job_id.name', 'ilike', 'bảo vệ'),
        ])
        self.assertEqual(len(guard_shift), 1)
        self.assertEqual(guard_shift.employee_ids, expected_guards)
        self.assertEqual(guard_shift.shift_type, 'full_day')

    def test_week_wizard_creates_separate_daily_assignments(self):
        start_date = fields.Date.context_today(self.env.user) + timedelta(days=7)
        wizard = self.env['spa.work.shift.week.wizard'].create({
            'start_date': start_date,
        })

        self.assertEqual(len(wizard.line_ids), 7)
        self.assertEqual(wizard.end_date, start_date + timedelta(days=6))
        wizard.line_ids[0].employee_ids = self.employee
        wizard.line_ids[1].employee_ids = self.guard
        wizard.action_apply()

        shifts = self.env['spa.work.shift'].search([
            ('work_date', '>=', start_date),
            ('work_date', '<=', start_date + timedelta(days=6)),
            ('auto_generated', '=', False),
            ('state', '=', 'scheduled'),
        ])
        self.assertEqual(len(shifts), 2)
        first_shift = shifts.filtered(
            lambda shift: shift.work_date == start_date
        )
        second_shift = shifts.filtered(
            lambda shift: shift.work_date == start_date + timedelta(days=1)
        )
        self.assertEqual(first_shift.employee_ids, self.employee)
        self.assertEqual(second_shift.employee_ids, self.guard)

    def test_week_wizard_omits_empty_employee_commands(self):
        start_date = fields.Date.context_today(self.env.user) + timedelta(
            days=3650
        )
        line_commands = self.env[
            'spa.work.shift.week.wizard'
        ]._prepare_week_lines(start_date)

        self.assertEqual(len(line_commands), 7)
        self.assertTrue(all(
            'employee_ids' not in command[2]
            for command in line_commands
        ))

    def test_week_wizard_prefills_existing_employees(self):
        start_date = fields.Date.context_today(self.env.user) + timedelta(
            days=3650
        )
        self._create_shift(work_date=start_date)
        line_commands = self.env[
            'spa.work.shift.week.wizard'
        ]._prepare_week_lines(start_date)
        wizard = self.env['spa.work.shift.week.wizard'].create({
            'start_date': start_date,
            'line_ids': line_commands,
        })

        self.assertEqual(wizard.line_ids[0].employee_ids, self.employee)

    def test_week_wizard_fills_dates_omitted_by_form(self):
        start_date = fields.Date.context_today(self.env.user) + timedelta(
            days=3650
        )
        wizard = self.env['spa.work.shift.week.wizard'].create({
            'start_date': start_date,
            'line_ids': [
                fields.Command.create({})
                for _offset in range(7)
            ],
        })
        lines = wizard.line_ids.sorted('day_offset')

        self.assertEqual(
            lines.mapped('day_offset'),
            list(range(7)),
        )
        self.assertEqual(
            lines.mapped('work_date'),
            [start_date + timedelta(days=offset) for offset in range(7)],
        )

    def test_shift_date_and_hours_follow_selected_local_date(self):
        work_date = fields.Date.context_today(self.env.user) + timedelta(days=10)
        shift = self.env['spa.work.shift'].with_context(
            tz='Asia/Ho_Chi_Minh',
        ).create({
            'name': 'Ca theo ngày địa phương',
            'work_date': work_date,
            'employee_ids': [(4, self.employee.id)],
        })
        work_date += timedelta(days=1)
        shift.write({'work_date': work_date})

        local_start = fields.Datetime.context_timestamp(
            shift, shift.start_datetime
        )
        local_end = fields.Datetime.context_timestamp(
            shift, shift.end_datetime
        )
        self.assertEqual(shift.work_date, work_date)
        self.assertEqual(local_start.date(), work_date)
        self.assertEqual(local_end.date(), work_date)
        self.assertEqual(local_start.time().hour, 7)
        self.assertEqual(local_end.time().hour, 19)
