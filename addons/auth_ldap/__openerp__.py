# Part of Odoo. See LICENSE file for full copyright and licensing details.

{
    'name' : 'Authentication via LDAP',
    'depends' : ['base'],
    'category' : 'Authentication',
    'data' : [
        'views/res_company_views.xml',
        'views/ldap_installer_views.xml',
        'security/ir.model.access.csv',
    ],
    'external_dependencies' : {
        'python' : ['ldap'],
    }
}
