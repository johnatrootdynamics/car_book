import * as WebBrowser from 'expo-web-browser';
import { useFocusEffect, useLocalSearchParams, router } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type Tag = { id: number; serial: string; status: string; activated_at?: string | null; car?: Car | null };
type OpenOrder = { id: number; number: string; payment_status: string; fulfillment_status: string };
type RfidCar = Car & { tag?: Tag | null; open_order?: OpenOrder | null };
type Shipping = { name: string; street: string; city: string; state: string; postal_code: string };
type Order = {
  id: number;
  number: string;
  amount: number;
  payment_method: string;
  payment_mode: string;
  payment_status: string;
  fulfillment_status: string;
  created_at: string;
  items: { id: number; car: Car; unit_price: number; tag?: Tag | null }[];
};
type RfidData = {
  unit_price: number;
  cars: RfidCar[];
  tags: Tag[];
  orders: Order[];
  payment_methods: { provider: string; label: string }[];
  shipping: Shipping;
};
type CheckoutResponse = { order: Order; completed: boolean; checkout_url?: string; return_url?: string };

export default function RfidScreen() {
  const params = useLocalSearchParams<{ checkout_status?: string; order_id?: string }>();
  const { account, api } = useAuth();
  const [data, setData] = useState<RfidData | null>(null);
  const [selected, setSelected] = useState<number[]>([]);
  const [provider, setProvider] = useState('');
  const [shipping, setShipping] = useState<Shipping>({ name: '', street: '', city: '', state: '', postal_code: '' });
  const [serial, setSerial] = useState('');
  const [activationCode, setActivationCode] = useState('');
  const [activationCarId, setActivationCarId] = useState<number | null>(null);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const body = await api<RfidData>('/driver/rfid');
      setData(body);
      setShipping(current => current.name ? current : body.shipping);
      setProvider(current => current || body.payment_methods[0]?.provider || '');
      setActivationCarId(current => current || body.cars[0]?.id || null);
      setSelected(current => current.filter(id => body.cars.some(car => car.id === id && !car.tag && !car.open_order)));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load RFID tags.');
    }
  }, [api]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => {
    const orderId = Number(params.order_id || 0);
    if (!orderId) return;
    api<{ order: Order }>(`/driver/rfid/orders/${orderId}`).then(body => {
      if (body.order.payment_status === 'paid') setNotice('Payment confirmed. Your RFID tag order is ready for fulfillment.');
      else if (params.checkout_status === 'canceled') setNotice('Checkout was canceled. No tag order was charged.');
      else setNotice('Payment is still processing. This page will update when it is confirmed.');
      return load();
    }).catch(caught => setError(caught instanceof Error ? caught.message : 'Unable to confirm the order.'));
  }, [api, load, params.checkout_status, params.order_id]);

  const availableCars = data?.cars.filter(car => !car.tag && !car.open_order) || [];
  const selectedCars = useMemo(() => availableCars.filter(car => selected.includes(car.id)), [availableCars, selected]);
  const total = (data?.unit_price || 0) * selectedCars.length;
  const addressComplete = Object.values(shipping).every(value => value.trim());
  const toggleCar = (carId: number) => setSelected(current => current.includes(carId) ? current.filter(id => id !== carId) : [...current, carId]);

  const purchase = async () => {
    if (!selected.length) return;
    setBusy('purchase'); setError(''); setNotice('');
    try {
      const result = await api<CheckoutResponse>('/driver/rfid/orders', {
        method: 'POST',
        body: JSON.stringify({ car_ids: selected, payment_method: provider, shipping }),
      });
      if (result.completed) {
        setSelected([]); setNotice('Your RFID tag order has been placed.'); await load(); return;
      }
      if (!result.checkout_url || !result.return_url) throw new Error('The payment provider did not return a checkout link.');
      const browserResult = await WebBrowser.openAuthSessionAsync(result.checkout_url, result.return_url);
      if (browserResult.type === 'success') {
        const status = await api<{ order: Order }>(`/driver/rfid/orders/${result.order.id}`);
        setNotice(status.order.payment_status === 'paid' ? 'Payment confirmed. Your tag order is ready for fulfillment.' : 'Payment is still processing.');
      } else {
        setNotice('No payment was completed. You can start a new order when ready.');
      }
      setSelected([]); await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to place the RFID tag order.');
    } finally { setBusy(''); }
  };

  const activate = async () => {
    if (!activationCarId) return;
    setBusy('activate'); setError(''); setNotice('');
    try {
      const result = await api<{ message: string }>('/driver/rfid/activate', {
        method: 'POST',
        body: JSON.stringify({ serial, activation_code: activationCode, car_id: activationCarId }),
      });
      setSerial(''); setActivationCode(''); setNotice(result.message); await load();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to activate that tag.');
    } finally { setBusy(''); }
  };

  if (account?.type !== 'user') return <Screen><Empty title="Driver account required" detail="RFID vehicle tags belong to driver garage accounts." /></Screen>;
  if (!data && !error) return <Loading />;
  if (!data) return <Screen><Empty title="RFID tags unavailable" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={load} /></Screen>;

  return <Screen>
    <Hero eyebrow="Your garage" title="RFID vehicle tags" subtitle="Order a windshield tag, activate it when it arrives, and use it for automatic track entry." />
    {notice ? <Notice tone="success" text={notice} /> : null}
    {error ? <Notice tone="error" text={error} /> : null}

    <SectionTitle title="Your vehicles" action={<Text style={styles.price}>{money(data.unit_price)} each</Text>} />
    {data.cars.length ? <View style={styles.stack}>{data.cars.map(car => {
      const selectable = !car.tag && !car.open_order;
      const isSelected = selected.includes(car.id);
      return <Pressable key={car.id} disabled={!selectable} onPress={() => toggleCar(car.id)} style={({ pressed }) => [styles.carRow, isSelected && styles.selectedRow, pressed && styles.pressed, !selectable && styles.disabledRow]}>
        <View style={[styles.carBadge, isSelected && styles.selectedBadge]}><Text style={styles.carLetters}>{car.make.slice(0, 1)}{car.model.slice(0, 1)}</Text></View>
        <View style={styles.grow}><Text style={styles.rowTitle}>{car.label}</Text><Text style={ui.body}>{car.tag ? `${car.tag.serial} · Active` : car.open_order ? orderLabel(car.open_order) : 'Tap to include this vehicle'}</Text></View>
        {car.tag ? <Status text="Active" good /> : car.open_order ? <Status text={car.open_order.fulfillment_status === 'fulfilled' ? 'Ready to activate' : 'Ordered'} good={car.open_order.payment_status === 'paid'} /> : <View style={[styles.check, isSelected && styles.checkSelected]}>{isSelected ? <Text style={styles.checkmark}>✓</Text> : null}</View>}
      </Pressable>;
    })}</View> : <Empty title="No cars in your garage" detail="Add a car before ordering an RFID vehicle tag." />}
    {!data.cars.length ? <Button title="Add a car" onPress={() => router.push('/car/new')} /> : null}

    {selectedCars.length ? <>
      <SectionTitle title="Ship your tags" />
      <Card style={styles.form}>
        <View><Text style={ui.label}>Full name</Text><Field value={shipping.name} onChangeText={value => setShipping({ ...shipping, name: value })} /></View>
        <View><Text style={ui.label}>Street address</Text><Field value={shipping.street} onChangeText={value => setShipping({ ...shipping, street: value })} /></View>
        <View style={styles.formRow}><View style={styles.grow}><Text style={ui.label}>City</Text><Field value={shipping.city} onChangeText={value => setShipping({ ...shipping, city: value })} /></View><View style={styles.stateField}><Text style={ui.label}>State</Text><Field autoCapitalize="characters" value={shipping.state} onChangeText={value => setShipping({ ...shipping, state: value })} /></View></View>
        <View><Text style={ui.label}>Postal code</Text><Field autoCapitalize="characters" value={shipping.postal_code} onChangeText={value => setShipping({ ...shipping, postal_code: value })} /></View>
      </Card>
      {total > 0 ? <><SectionTitle title="Payment method" /><View style={styles.stack}>{data.payment_methods.map(method => <Pressable key={method.provider} onPress={() => setProvider(method.provider)} style={[styles.method, provider === method.provider && styles.selectedRow]}><View style={[styles.providerMark, method.provider === 'paypal' ? styles.paypal : styles.stripe]}><Text style={styles.providerLetter}>{method.provider === 'paypal' ? 'P' : 'S'}</Text></View><View style={styles.grow}><Text style={styles.rowTitle}>{method.label}</Text><Text style={ui.body}>{method.provider === 'paypal' ? 'Finish securely with PayPal' : 'Credit or debit card through Stripe'}</Text></View><View style={[styles.radio, provider === method.provider && styles.radioSelected]} /></Pressable>)}</View></> : null}
      <Card style={styles.summary}><View style={ui.between}><Text style={ui.body}>{selectedCars.length} vehicle tag{selectedCars.length === 1 ? '' : 's'}</Text><Text style={styles.summaryValue}>{money(total)}</Text></View><View style={styles.rule} /><View style={ui.between}><Text style={styles.totalLabel}>Total</Text><Text style={styles.total}>{money(total)}</Text></View></Card>
      <Button title={busy === 'purchase' ? 'Opening secure checkout…' : total <= 0 ? 'Place free tag order' : `Pay ${money(total)}`} disabled={busy !== '' || !addressComplete || (total > 0 && !provider)} onPress={purchase} />
      {total > 0 && !data.payment_methods.length ? <Text style={styles.errorText}>Enterprise tag payments have not been configured yet.</Text> : null}
    </> : null}

    <SectionTitle title="Activate a delivered tag" />
    <Card style={styles.form}>
      <Text style={ui.body}>Use the serial and one-time activation code from the fulfillment email.</Text>
      <View><Text style={ui.label}>Tag serial</Text><Field autoCapitalize="characters" autoCorrect={false} placeholder="TAG-12AB34CD" value={serial} onChangeText={setSerial} /></View>
      <View><Text style={ui.label}>Activation code</Text><Field autoCapitalize="characters" autoCorrect={false} placeholder="XXXX-XXXX-XXXX" value={activationCode} onChangeText={setActivationCode} /></View>
      <Text style={ui.label}>Assign to vehicle</Text>
      <View style={styles.chips}>{data.cars.filter(car => !car.tag).map(car => <Pressable key={car.id} onPress={() => setActivationCarId(car.id)} style={[styles.chip, activationCarId === car.id && styles.chipActive]}><Text style={[styles.chipText, activationCarId === car.id && styles.chipTextActive]} numberOfLines={1}>{car.year} {car.make} {car.model}</Text></Pressable>)}</View>
      <Button title={busy === 'activate' ? 'Activating…' : 'Activate tag'} disabled={busy !== '' || !serial.trim() || !activationCode.trim() || !activationCarId} onPress={activate} />
    </Card>

    <SectionTitle title="Recent orders" />
    {data.orders.length ? data.orders.slice(0, 6).map(order => <Card key={order.id} style={styles.orderCard}><View style={ui.between}><View><Text style={styles.rowTitle}>{order.number}</Text><Text style={ui.body}>{order.items.length} tag{order.items.length === 1 ? '' : 's'} · {money(order.amount)}</Text></View><Status text={order.fulfillment_status === 'fulfilled' ? 'Fulfilled' : order.payment_status === 'paid' ? 'Paid' : titleCase(order.payment_status)} good={order.payment_status === 'paid'} /></View><Text style={styles.orderCars}>{order.items.map(item => item.car.label).join(' · ')}</Text></Card>) : <Empty title="No tag orders" detail="Select a vehicle above to order its first RFID tag." />}
  </Screen>;
}

function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: tone === 'success' ? palette.green : palette.red }]}>{text}</Text></View>; }
function Status({ text, good = false }: { text: string; good?: boolean }) { return <Text style={[styles.status, good ? styles.goodStatus : styles.waitStatus]}>{text}</Text>; }
function money(value: number) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value || 0); }
function titleCase(value: string) { return value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase()); }
function orderLabel(order: OpenOrder) { if (order.fulfillment_status === 'fulfilled') return `${order.number} · Ready to activate`; if (order.payment_status === 'paid') return `${order.number} · Waiting for shipment`; return `${order.number} · ${titleCase(order.payment_status)}`; }

const styles = StyleSheet.create({
  stack: { gap: 9 }, grow: { flex: 1 }, pressed: { opacity: .65 }, disabledRow: { opacity: .78 }, price: { color: palette.orange, fontWeight: '900' },
  carRow: { minHeight: 78, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 13, borderRadius: 17, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surface }, selectedRow: { borderColor: palette.orange, backgroundColor: '#FFF9F5' },
  carBadge: { width: 48, height: 48, borderRadius: 14, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, selectedBadge: { backgroundColor: palette.orange }, carLetters: { color: 'white', fontWeight: '900' }, rowTitle: { color: palette.ink, fontSize: 15, fontWeight: '900' },
  check: { width: 24, height: 24, borderRadius: 12, borderWidth: 2, borderColor: '#D0D5DD', alignItems: 'center', justifyContent: 'center' }, checkSelected: { backgroundColor: palette.orange, borderColor: palette.orange }, checkmark: { color: 'white', fontWeight: '900' },
  status: { overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 5, borderRadius: 999, fontSize: 10, fontWeight: '900' }, goodStatus: { color: palette.green, backgroundColor: palette.greenSoft }, waitStatus: { color: '#B54708', backgroundColor: '#FFFAEB' },
  form: { gap: 13 }, formRow: { flexDirection: 'row', gap: 10 }, stateField: { width: 92 }, method: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 12, padding: 12, borderRadius: 17, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surface }, providerMark: { width: 44, height: 44, borderRadius: 13, alignItems: 'center', justifyContent: 'center' }, paypal: { backgroundColor: '#003087' }, stripe: { backgroundColor: '#635BFF' }, providerLetter: { color: 'white', fontWeight: '900', fontSize: 20 }, radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: '#D0D5DD' }, radioSelected: { borderColor: palette.orange, borderWidth: 7 },
  summary: { gap: 13 }, summaryValue: { color: palette.ink, fontWeight: '800' }, rule: { height: 1, backgroundColor: palette.line }, totalLabel: { color: palette.ink, fontWeight: '900', fontSize: 17 }, total: { color: palette.orange, fontWeight: '900', fontSize: 24 },
  chips: { gap: 8 }, chip: { minHeight: 42, justifyContent: 'center', paddingHorizontal: 12, borderRadius: 12, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white' }, chipActive: { backgroundColor: palette.navy, borderColor: palette.navy }, chipText: { color: palette.ink, fontWeight: '800' }, chipTextActive: { color: 'white' },
  orderCard: { gap: 10 }, orderCars: { color: palette.muted, fontSize: 12, lineHeight: 18 }, notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800', lineHeight: 20 }, errorText: { color: palette.red, fontWeight: '800', textAlign: 'center' },
});
