# -*- coding: utf-8 -*-
# Part of Odoo. See LICENSE file for full copyright and licensing details.
{
    'name': 'HR Gamification',
    'version': '1.0',
    'category': 'hidden',
    'website': 'https://www.odoo.com/page/employees',
    'depends': ['gamification', 'hr'],
    'description': """Use the HR resources for the gamification process.

The HR officer can now manage challenges and badges.
This allow the user to send badges to employees instead of simple users.
Badge received are displayed on the user profile.
""",
    'data': [
        'security/ir.model.access.csv',
        'security/hr_gamification_security.xml',
        'wizard/gamification_badge_views.xml',
        'views/gamification_views.xml',
        'views/hr_gamification_templates.xml',
    ],
    'auto_install': True,
}
