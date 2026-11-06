def migrate(cr, version):
    cr.execute("SELECT to_regclass('spa_customer')")
    if cr.fetchone()[0]:
        cr.execute(
            "DROP TABLE IF EXISTS spa_customer_spa_customer_batch_update_wizard_rel",
        )
        cr.execute("DROP TABLE spa_customer")
