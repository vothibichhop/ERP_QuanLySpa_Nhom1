from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    cr.execute("SELECT to_regclass('spa_customer')")
    if not cr.fetchone()[0]:
        return

    cr.execute("""
        CREATE TABLE spa_customer_partner_map (
            customer_id integer PRIMARY KEY,
            partner_id integer,
            customer_code varchar,
            birthday date,
            gender varchar
        )
    """)
    cr.execute("SELECT to_regclass('spa_appointment')")
    has_appointments = bool(cr.fetchone()[0])
    if has_appointments:
        cr.execute("""
            ALTER TABLE spa_appointment
            DROP CONSTRAINT IF EXISTS spa_appointment_customer_id_fkey
        """)

    env = api.Environment(cr, SUPERUSER_ID, {})
    cr.execute("""
        SELECT id, customer_code, birthday, gender,
               name, phone, address, note, active
          FROM spa_customer
         ORDER BY id
    """)
    for customer_id, code, birthday, gender, name, phone, address, note, active in cr.fetchall():
        partner = env['res.partner'].create({
            'name': name,
            'phone': phone,
            'street': address,
            'comment': note,
            'active': active if active is not None else True,
            'is_company': False,
        })
        cr.execute("""
            INSERT INTO spa_customer_partner_map (
                customer_id, partner_id, customer_code, birthday, gender
            )
            VALUES (%s, %s, %s, %s, %s)
        """, [customer_id, partner.id, code, birthday, gender])

    if has_appointments:
        cr.execute("""
            UPDATE spa_appointment appointment
               SET customer_id = partner_map.partner_id
              FROM spa_customer_partner_map partner_map
             WHERE appointment.customer_id = partner_map.customer_id
        """)
