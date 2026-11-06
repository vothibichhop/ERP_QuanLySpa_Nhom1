def migrate(cr, version):
    cr.execute(
        """
        UPDATE customer_care_need AS care_need
           SET employee_id = (
               SELECT employee.id
                 FROM hr_employee AS employee
                WHERE employee.user_id = care_need.user_id
                ORDER BY employee.active DESC, employee.id
                LIMIT 1
           )
         WHERE care_need.user_id IS NOT NULL
           AND care_need.employee_id IS NULL
           AND EXISTS (
               SELECT 1
                 FROM hr_employee AS employee
                WHERE employee.user_id = care_need.user_id
           )
        """
    )
