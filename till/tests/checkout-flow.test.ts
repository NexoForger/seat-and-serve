import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { mount, flushPromises } from "@vue/test-utils";
import App from "../src/App.vue";
const api = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn(), id: 0 }));
vi.mock("../../ui/client", () => ({
  get: api.get,
  post: api.post,
  eventId: () => `event-${++api.id}`,
}));
let wrapper: ReturnType<typeof mount> | undefined;
let product: any;
let order: any;
beforeEach(() => {
  history.replaceState(null, "", "/till");
  api.get.mockReset();
  api.post.mockReset();
  product = {
    item: "ITEM-1",
    name_en: "Product",
    rate: 3,
    uom: "Nos",
    weighed: false,
  };
  order = {
    name: "ORDER-1",
    order_number: "1",
    revision: 1,
    status: "Draft",
    channel: "Till",
    outlet: "OUT",
    currency: "USD",
    lines: [],
    grand_total: 0,
    net_total: 0,
    tax_total: 0,
  };
  api.get.mockImplementation((method) =>
    Promise.resolve(
      method === "bootstrap"
        ? {
            outlets: [{ name: "OUT", title: "Outlet", base_currency: "USD", enable_delivery:1 }],
            roles: ["TRT Cashier"],
          }
        : method === "checkout_options"
          ? {
              cash_modes: ["Cash"],
              base_currency: "USD",
              enable_delivery: 1,
              opening_entry: "OPEN",
                fx_rate: {lbp_per_usd:89500},
            }
          : method === "register_tables"
            ? []
            : method === "catalog"
              ? { items: [product] }
              : product,
    ),
  );
  api.post.mockImplementation((_method, args) => {
    const command = args.command;
    if(command.action === 'create') Object.assign(order,{channel:command.channel,delivery_name:command.delivery_name,delivery_phone:command.delivery_phone,delivery_address:command.delivery_address});
    if (command.action === "add_line")
      order.lines.push({
        name: "LINE-1",
        item: "ITEM-1",
        item_name: "Product",
        qty: 1,
        rate: 3,
        amount: 3,
        uom: "Nos",
        modifiers: [],
      });
    if (command.action === "set_qty") order.lines[0].qty = command.qty;
    order.revision++;
    order.grand_total = (order.lines[0]?.qty || 0) * 3;
    return Promise.resolve(JSON.parse(JSON.stringify(order)));
  });
});
afterEach(() => wrapper?.unmount());
async function open() {
  wrapper = mount(App);
  await flushPromises();
  await wrapper
    .findAll(".register-type-card")
    .find((b) => b.text().includes("Counter"))!
    .trigger("click");
  await flushPromises();
}
async function scan() {
  const input = wrapper!.get(".checkout-scanner input");
  await input.setValue("00123");
  await input.trigger("keydown", { key: "Enter" });
  await flushPromises();
}
it("creates a bill on first scan and increments its plain line on the next scan", async () => {
  await open();
  await scan();
  expect(order.lines).toHaveLength(1);
  expect(order.lines[0].qty).toBe(1);
  await scan();
  expect(order.lines).toHaveLength(1);
  expect(order.lines[0].qty).toBe(2);
  expect(
    api.post.mock.calls.filter(([, args]) => args.command.action === "create"),
  ).toHaveLength(1);
  expect(api.get).toHaveBeenCalledWith("items.lookup_barcode", {
    outlet: "OUT",
    channel: "Till",
    barcode: "00123",
  });
});
it("keeps required modifiers in the existing picker and does not silently add", async () => {
  product.modifier_group = {
    name: "G",
    title: "Options",
    minimum: 1,
    options: [{ item: "OPT", name_en: "Option", price_delta: 0 }],
  };
  await open();
  await scan();
  expect(wrapper!.text()).toContain("Choose at least");
  expect(api.post).not.toHaveBeenCalled();
});
it("does not add an arbitrary quantity for a weighed barcode", async () => {
  product.weighed = true;
  await open();
  await scan();
  expect(wrapper!.text()).toContain("sold by weight");
  expect(api.post).not.toHaveBeenCalled();
});

it('shows the LBP equivalent beneath the USD total', async()=>{
  await open();await scan();expect(wrapper!.get('.register-total-lbp').text()).toContain('268,500');
});
it('creates a delivery bill with contact and address details', async()=>{
  wrapper=mount(App);await flushPromises();
  await wrapper.findAll('.register-type-card').find(button=>button.text().includes('Delivery'))!.trigger('click');await flushPromises();
  const inputs=wrapper.findAll('.register-delivery-form input');
  await inputs[0]!.setValue('Recipient');await inputs[1]!.setValue('+961123456');await wrapper.get('.register-delivery-form textarea').setValue('Beirut, Street 1, Floor 2');
  await wrapper.get('.register-delivery-form').trigger('submit');await flushPromises();await scan();
  const create=api.post.mock.calls.find(([,args])=>args.command.action==='create')![1].command;
  expect(create).toMatchObject({channel:'Delivery',delivery_name:'Recipient',delivery_phone:'+961123456',delivery_address:'Beirut, Street 1, Floor 2'});
  expect(wrapper!.get('.register-delivery-context').text()).toContain('Beirut');
});
it('switches mobile products/bill panes without losing the bill',async()=>{
  await open();await scan();
  await wrapper!.findAll('.register-mobile-switch button')[1]!.trigger('click');
  expect(wrapper!.get('.register-shell').classes()).toContain('register-mobile-bill');
  await wrapper!.findAll('.register-mobile-switch button')[0]!.trigger('click');
  expect(wrapper!.get('.register-shell').classes()).not.toContain('register-mobile-bill');expect(order.lines).toHaveLength(1);
});
