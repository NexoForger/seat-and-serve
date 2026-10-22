import {afterEach, expect, it, vi} from 'vitest';
import {mount, flushPromises} from '@vue/test-utils';
import App from '../src/App.vue';
const api=vi.hoisted(()=>({get:vi.fn(),post:vi.fn(),id:0}));
vi.mock('../../ui/client',()=>({get:api.get,post:api.post,eventId:()=>`pay-${++api.id}`}));
let wrapper:ReturnType<typeof mount>;
afterEach(()=>wrapper?.unmount());
it('reduces a tab balance, reopens it, and reuses a lost-response payment event',async()=>{
  history.replaceState(null,'','/till');
  const order:any={name:'TAB',order_number:'1',outlet:'OUT',channel:'Tab',tab_label:'Guest',currency:'USD',revision:2,status:'Sent',grand_total:100,lines:[{name:'LINE',item:'ITEM',item_name:'Product',qty:1,amount:100}],bill:{grand_total:100,amount_due:100,paid_amount:0,item_count:1,ticket_count:1,order_numbers:['1'],loyalty:{points:0},discount_amount:0}};
  const copy=()=>JSON.parse(JSON.stringify(order));
  api.get.mockImplementation(async(method)=>method==='bootstrap'?{outlets:[{name:'OUT',title:'Outlet',base_currency:'USD',enable_tabs:1}],roles:['TRT Cashier']}:method==='checkout_options'?{cash_modes:['Cash'],opening_entry:'OPEN',pos_invoice_mode:true}:method==='register_tabs'?[{...copy(),amount_due:order.bill.amount_due}]:method==='register_order'?copy():method==='catalog'?{items:[]}:{});
  let first=true;
  api.post.mockImplementation(async(method)=>{
    if(method!=='cash_checkout')throw new Error(method);
    if(first){first=false;Object.assign(order,{status:'Partially Paid',pos_invoice:'POS',revision:3});Object.assign(order.bill,{paid_amount:30,amount_due:70});throw new Error('Connection lost');}
    return copy();
  });
  wrapper=mount(App);await flushPromises();
  await wrapper.findAll('.register-type-card').find(b=>b.text().includes('Open tab'))!.trigger('click');await flushPromises();
  await wrapper.get('.register-table-card').trigger('click');await flushPromises();
  await wrapper.findAll('.register-actions button').find(b=>b.text().includes('Cash payment'))!.trigger('click');await flushPromises();
  await wrapper.get('.register-add-tender').trigger('click');
  await wrapper.get('.register-tender input').setValue(30);
  await wrapper.get('.register-confirm-payment').trigger('click');await flushPromises();
  await wrapper.get('.register-confirm-payment').trigger('click');await flushPromises();
  const calls=api.post.mock.calls.filter(([method])=>method==='cash_checkout');
  expect(calls).toHaveLength(2);expect(calls[0]![1]).toEqual(calls[1]![1]);
  expect(wrapper.text()).toContain('Remaining balance');expect(wrapper.text()).toContain('$70.00');
  expect(wrapper.get('.register-invoice').text()).toContain('Partially Paid');
  expect(wrapper.findAll('.register-actions button').find(b=>b.text().includes('Cash payment'))!.attributes('disabled')).toBeUndefined();
  expect(wrapper.find('.register-payment').exists()).toBe(false);
});
