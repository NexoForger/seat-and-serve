frappe.ui.form.on('TRT Staff Assignment', {
  refresh(frm) {
    if (frm.is_new() || !frappe.user.has_role('System Manager')) return;
    frm.add_custom_button(__('Set Till PIN'), () => {
      frappe.prompt([
        {fieldname: 'login_code', fieldtype: 'Data', label: __('Staff code'), reqd: 1, default: frm.doc.till_login_code || ''},
        {fieldname: 'pin_secret', fieldtype: 'Password', label: __('New PIN (6–12 digits)'), reqd: 1},
      ], async values => {
        await frappe.call({method: 'table_remote_till.pin_auth.set_pin', args: {assignment: frm.doc.name, ...values}, freeze: true});
        await frm.reload_doc();
        frappe.show_alert({message: __('Till PIN configured. Previous PIN sessions are revoked.'), indicator: 'green'});
      }, __('Set Till PIN'), __('Save PIN'));
    });
    if (frm.doc.till_pin_enabled) frm.add_custom_button(__('Revoke Till PIN'), () => {
      frappe.confirm(__('Disable PIN access and revoke existing PIN sessions?'), async () => {
        await frappe.call({method: 'table_remote_till.pin_auth.revoke_pin', args: {assignment: frm.doc.name}, freeze: true});
        await frm.reload_doc();
      });
    });
  },
});
