from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    employees = env['hr.employee'].with_context(active_test=False).search(
        [('employee_code', '=', False)],
        order='id',
    )
    sequence = env['ir.sequence']
    for employee in employees:
        code = sequence.next_by_code('spa.employee')
        if not code:
            raise RuntimeError(
                'Không tìm thấy sequence tạo mã nhân viên Spa.'
            )
        employee.employee_code = code
