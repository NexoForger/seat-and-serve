frappe.ui.form.on('TRT Device', {
  refresh(frm) {
    if (frm.doc.kind !== 'Receipt Printer') return;
    const usb = frm.doc.driver === 'escpos_usb';
    frm.set_df_property('address', 'label', usb ? __('USB printer queue') : __('Printer IP address'));
    frm.set_df_property('address', 'description', usb
      ? __('Local printer queue name on the printer host, for example Xprinter_USB.')
      : __('IPv4 address and optional port, for example 192.168.0.46:9100.'));
    frm.add_custom_button(__('Configure printer'), () => configure_printer(frm));
    if (frm.is_new() || !frm.doc.enabled) return;
    for (const [label, method] of [['Print test page', 'test_print'], ['Test cash drawer', 'test_drawer']]) {
      frm.add_custom_button(__(label), async () => {
        if (frm.is_dirty()) {
          frappe.msgprint(__('Save the printer settings before testing.'));
          return;
        }
        const result = await frappe.call({ method: `table_remote_till.printer_api.${method}`,
          args: { device_name: frm.doc.name }, freeze: true });
        frappe.msgprint(result.message.status === 'Pending'
          ? __('Job waiting for the printer PC/Pi. Check TRT Print Job for delivery status.')
          : result.message.status === 'Queued'
          ? __('USB job accepted by the print queue. Check the physical result; an offline queue may process it later.')
          : __('Command sent to the printer. Check the physical result.'));
      });
    }
  },
});

function configure_printer(frm) {
  let settings;
  try { settings = JSON.parse(frm.doc.settings_json || '{}'); }
  catch { frappe.msgprint(__('Correct Settings JSON before configuring the printer.')); return; }
  if (!settings || Array.isArray(settings) || typeof settings !== 'object') {
    frappe.msgprint(__('Settings JSON must be an object.'));
    return;
  }
  const dialog = new frappe.ui.Dialog({
    title: __('Receipt printer and cash drawer'),
    fields: [
      { fieldname: 'print_from', label: __('Printer host'), fieldtype: 'Select',
        options: 'Local PC / Pi agent\nERP server',
        default: settings.print_agent || frm.is_new() ? 'Local PC / Pi agent' : 'ERP server',
        description: __('Use a local agent when the ERP is hosted remotely. The agent connects outward over HTTPS.') },
      { fieldname: 'print_agent', label: __('Print agent name'), fieldtype: 'Data',
        default: settings.print_agent || '', depends_on: "eval:doc.print_from === 'Local PC / Pi agent'",
        mandatory_depends_on: "eval:doc.print_from === 'Local PC / Pi agent'",
        description: __('For example register-1. Match the agent configured on the printer PC/Pi.') },
      { fieldname: 'connection', label: __('Connection'), fieldtype: 'Select', options: 'LAN / Ethernet\nUSB',
        default: frm.doc.driver === 'escpos_usb' ? 'USB' : 'LAN / Ethernet', reqd: 1 },
      { fieldname: 'lan_address', label: __('Printer IP and port'), fieldtype: 'Data',
        default: frm.doc.driver !== 'escpos_usb' ? frm.doc.address : '',
        depends_on: "eval:doc.connection !== 'USB'", mandatory_depends_on: "eval:doc.connection !== 'USB'",
        description: __('For example 192.168.0.46:9100') },
      { fieldname: 'usb_queue', label: __('USB printer queue'), fieldtype: 'Data',
        default: frm.doc.driver === 'escpos_usb' ? frm.doc.address : '',
        depends_on: "eval:doc.connection === 'USB'", mandatory_depends_on: "eval:doc.connection === 'USB'",
        description: __('Queue name on the printer PC/Pi: CUPS on Mac/Linux or an installed Windows printer.') },
      { fieldname: 'auto_cut', label: __('Cut receipt after printing'), fieldtype: 'Check', default: settings.auto_cut !== false },
      { fieldname: 'drawer_enabled', label: __('Open cash drawer after a cash payment'), fieldtype: 'Check', default: !!settings.drawer_enabled },
      { fieldname: 'drawer_pin', label: __('Drawer output'), fieldtype: 'Select', options: 'Pin 2 (output 1)\nPin 5 (output 2)',
        default: settings.drawer_pin === 1 ? 'Pin 5 (output 2)' : 'Pin 2 (output 1)', depends_on: 'drawer_enabled' },
      { fieldname: 'drawer_pulse_ms', label: __('Pulse duration (ms)'), fieldtype: 'Int',
        default: settings.drawer_pulse_ms || 100, depends_on: 'drawer_enabled',
        description: __('Even number from 20 to 250. Default 100. USB queue jobs may be delayed while the printer is offline.') },
    ],
    primary_action_label: __('Save printer'),
    async primary_action(values) {
      await frm.set_value({
        driver: values.connection === 'USB' ? 'escpos_usb' : 'escpos_tcp',
        address: values.connection === 'USB' ? values.usb_queue : values.lan_address,
        settings_json: JSON.stringify({ ...settings, auto_cut: !!values.auto_cut,
          print_agent: values.print_from === 'Local PC / Pi agent' ? values.print_agent : '',
          drawer_enabled: !!values.drawer_enabled, drawer_pin: values.drawer_pin === 'Pin 5 (output 2)' ? 1 : 0,
          drawer_pulse_ms: values.drawer_pulse_ms || 100 }, null, 2),
      });
      await frm.save();
      dialog.hide();
    },
  });
  dialog.show();
}
