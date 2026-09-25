frappe.ui.form.on('TRT Import Job', {
  refresh(frm) {
    frm.set_intro(__('1. Attach a private CSV/XLSX export. 2. Map column names in Mapping JSON. 3. Preview and resolve errors. 4. Import supported master records. Historical exports are staged for reconciliation; transaction import is not yet available.'));
    if (frm.is_new()) return;
    frm.add_custom_button(__('Suggest columns'), async () => {
      const result = await frappe.call({ method: 'table_remote_till.migration.suggest_mapping',
        args: { job_name: frm.doc.name } });
      const current = frm.doc.mapping_json ? JSON.parse(frm.doc.mapping_json) : {};
      frm.set_value('mapping_json', JSON.stringify({ ...result.message.mapping, ...current }, null, 2));
      frappe.msgprint(__('Review suggested column mappings before previewing.'));
    });
    frm.add_custom_button(__('Preview mapping'), async () => {
      const result = await frappe.call({
        method: 'table_remote_till.migration.preview',
        args: { job_name: frm.doc.name, mapping_json: frm.doc.mapping_json },
      });
      frappe.msgprint({ title: __('Preview'),
        message: `<pre>${frappe.utils.escape_html(JSON.stringify(result.message, null, 2))}</pre>`,
        wide: true });
      frm.reload_doc();
    });
    frm.add_custom_button(__('Source inventory'), async () => {
      const result = await frappe.call({
        method: 'table_remote_till.migration.source_inventory',
        args: { source: frm.doc.source },
      });
      frappe.msgprint({ title: __('Available exports'),
        message: `<pre>${frappe.utils.escape_html(JSON.stringify(result.message, null, 2))}</pre>`,
        wide: true });
    });
    if (frm.doc.status === 'Validated' && ['Item', 'Customer', 'Supplier'].includes(frm.doc.record_type)) {
      frm.add_custom_button(__('Import masters'), async () => {
        const result = await frappe.call({
          method: 'table_remote_till.migration.import_masters',
          args: { job_name: frm.doc.name },
        });
        frappe.msgprint(JSON.stringify(result.message));
        frm.reload_doc();
      });
    }
  },
});
