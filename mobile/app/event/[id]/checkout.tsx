import * as WebBrowser from 'expo-web-browser';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Car, TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type PaymentMethod = { provider: string; label: string };
type CheckoutData = {
  event: TrackEvent;
  cars: Car[];
  payment_methods: PaymentMethod[];
  buyer: { name: string; email: string };
};
type Order = {
  id: number;
  event_id: number;
  amount: number;
  payment_method: string;
  payment_mode: string;
  payment_status: string;
  failure_reason?: string | null;
};
type CheckoutResponse = {
  order: Order;
  completed: boolean;
  checkout_url?: string;
  return_url: string;
};

export default function DriverCheckoutScreen() {
  const params = useLocalSearchParams<{ id: string; checkout_status?: string; order_id?: string }>();
  const eventId = Number(params.id);
  const { account, api } = useAuth();
  const [data, setData] = useState<CheckoutData | null>(null);
  const [carId, setCarId] = useState<number | null>(null);
  const [provider, setProvider] = useState('');
  const [order, setOrder] = useState<Order | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  const load = useCallback(async () => {
    if (account?.type !== 'user' || !eventId) return;
    setLoading(true); setError('');
    try {
      const body = await api<CheckoutData>(`/driver/events/${eventId}/checkout`);
      setData(body);
      setCarId(current => current && body.cars.some(car => car.id === current) ? current : body.cars[0]?.id || null);
      setProvider(current => current && body.payment_methods.some(method => method.provider === current) ? current : body.payment_methods[0]?.provider || '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to prepare checkout.');
    } finally { setLoading(false); }
  }, [account, api, eventId]);

  const refreshOrder = useCallback(async (orderId: number) => {
    const body = await api<{ order: Order }>(`/driver/orders/${orderId}`);
    setOrder(body.order);
    if (body.order.payment_status === 'paid') {
      setNotice('Payment confirmed. Your driver ticket and QR code are ready.');
      setError('');
    } else if (body.order.payment_status === 'failed') {
      setError(body.order.failure_reason || 'The payment could not be completed.');
    } else if (body.order.payment_status === 'canceled') {
      setNotice('Checkout was canceled. You can start again when ready.');
    } else {
      setNotice('Payment is still processing. Your ticket will appear as soon as it is confirmed.');
    }
    return body.order;
  }, [api]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => {
    const returnedOrderId = Number(params.order_id || 0);
    if (!returnedOrderId) return;
    refreshOrder(returnedOrderId).catch(caught => setError(caught instanceof Error ? caught.message : 'Unable to check payment status.'));
  }, [params.checkout_status, params.order_id, refreshOrder]);

  const purchase = async () => {
    if (!carId || !provider) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<CheckoutResponse>(`/driver/events/${eventId}/checkout`, {
        method: 'POST',
        body: JSON.stringify({ car_id: carId, payment_method: provider }),
      });
      setOrder(result.order);
      if (result.completed) {
        setNotice('Your driver ticket and QR code are ready.');
        return;
      }
      if (!result.checkout_url) throw new Error('The payment provider did not return a checkout link.');
      const browserResult = await WebBrowser.openAuthSessionAsync(result.checkout_url, result.return_url);
      if (browserResult.type === 'success') {
        await refreshOrder(result.order.id);
      } else {
        setNotice('No payment was completed. You can resume checkout when ready.');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to start checkout.');
    } finally { setBusy(false); }
  };

  if (account?.type !== 'user') return <Screen><Empty title="Driver account required" detail="Sign in as a driver to purchase admission." /></Screen>;
  if (loading && !data && !order) return <Loading />;
  if (order?.payment_status === 'paid') return <Screen>
    <Hero eyebrow="Payment confirmed" title="You’re going racing" subtitle="Your registration is complete and the ticket QR code is ready in the app." />
    <Card style={styles.successCard}><View style={styles.successIcon}><SymbolView name={{ ios: 'checkmark', android: 'checkmark', web: 'checkmark' } as any} tintColor="white" size={28} /></View><Text style={styles.successTitle}>Driver ticket confirmed</Text><Text style={styles.centerCopy}>We also sent the ticket to your email. Bring the QR code to check-in and inspection.</Text></Card>
    <Button title="View ticket for this event" onPress={() => router.replace({ pathname: '/(tabs)/tickets', params: { eventId: String(eventId) } })} />
    <Button tone="secondary" title="Back to event" onPress={() => router.replace(`/event/${eventId}`)} />
  </Screen>;
  if (!data) return <Screen><BackButton eventId={eventId} /><Empty title="Checkout unavailable" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={load} /></Screen>;

  const remaining = data.event.availability?.driver;
  const selectedCar = data.cars.find(car => car.id === carId);
  const selectedMethod = data.payment_methods.find(method => method.provider === provider);
  return <Screen>
    <BackButton eventId={eventId} />
    <Hero eyebrow="Driver admission" title={data.event.name} subtitle={`${eventDate(data.event.date)} · ${data.event.track.name}`} />
    {notice ? <Notice tone="success" text={notice} /> : null}
    {error ? <Notice tone="error" text={error} /> : null}

    <SectionTitle title="Choose your car" action={!data.cars.length ? <Pressable onPress={() => router.push('/car/new')}><Text style={styles.addCar}>+ Add car</Text></Pressable> : undefined} />
    {data.cars.length ? <View style={styles.options}>{data.cars.map(car => <Pressable key={car.id} onPress={() => setCarId(car.id)} style={({ pressed }) => [styles.option, carId === car.id && styles.optionSelected, pressed && styles.pressed]}><View style={[styles.carBadge, carId === car.id && styles.carBadgeSelected]}><Text style={[styles.carLetters, carId === car.id && styles.carLettersSelected]}>{car.make.slice(0, 1)}{car.model.slice(0, 1)}</Text></View><View style={styles.optionCopy}><Text style={styles.optionTitle}>{car.label}</Text><Text style={ui.body}>{car.color || 'Color not listed'}</Text></View><Selection selected={carId === car.id} /></Pressable>)}</View> : <Empty title="Add a car first" detail="Every driver ticket is connected to the vehicle you will bring to the event." />}

    <SectionTitle title="Payment method" />
    {data.payment_methods.length ? <View style={styles.options}>{data.payment_methods.map(method => <Pressable key={method.provider} onPress={() => setProvider(method.provider)} style={({ pressed }) => [styles.option, provider === method.provider && styles.optionSelected, pressed && styles.pressed]}><ProviderMark provider={method.provider} /><View style={styles.optionCopy}><Text style={styles.optionTitle}>{method.label}</Text><Text style={ui.body}>{providerDetail(method.provider, data.event.prices.driver)}</Text></View><Selection selected={provider === method.provider} /></Pressable>)}</View> : <Empty title="Payment is not configured" detail="This track has not enabled a payment method for driver admission yet." />}

    <SectionTitle title="Order summary" />
    <Card style={styles.summary}>
      <View style={styles.summaryRow}><Text style={ui.body}>Driver admission</Text><Text style={styles.summaryValue}>{money(data.event.prices.driver)}</Text></View>
      <View style={styles.summaryRow}><Text style={ui.body}>Driver</Text><Text style={styles.summaryValue}>{data.buyer.name}</Text></View>
      <View style={styles.summaryRow}><Text style={ui.body}>Vehicle</Text><Text numberOfLines={1} style={styles.summaryValue}>{selectedCar?.label || 'Select a car'}</Text></View>
      <View style={styles.divider} />
      <View style={styles.totalRow}><Text style={styles.totalLabel}>Total</Text><Text style={styles.total}>{money(data.event.prices.driver)}</Text></View>
      <Text style={styles.capacity}>{remaining?.unlimited ? 'Driver capacity is open' : `${remaining?.remaining ?? 0} driver spot${remaining?.remaining === 1 ? '' : 's'} remaining`}</Text>
    </Card>

    <Button title={busy ? 'Opening secure checkout…' : data.event.prices.driver <= 0 ? 'Confirm free driver ticket' : `Pay ${money(data.event.prices.driver)} with ${selectedMethod?.label || 'provider'}`} onPress={purchase} disabled={busy || !carId || !provider || !data.payment_methods.length} />
    <Text style={styles.footnote}>One driver ticket per account. Your ticket is issued only after the payment provider confirms the charge.</Text>
  </Screen>;
}

function BackButton({ eventId }: { eventId: number }) { return <Pressable accessibilityRole="button" onPress={() => router.canGoBack() ? router.back() : router.replace(`/event/${eventId}`)} style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}><Text style={styles.backArrow}>‹</Text><Text style={styles.backText}>Event</Text></Pressable>; }
function Selection({ selected }: { selected: boolean }) { return <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>; }
function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: tone === 'success' ? palette.green : palette.red }]}>{text}</Text></View>; }
function ProviderMark({ provider }: { provider: string }) { const colors = provider === 'paypal' ? ['#003087', '#009CDE'] : provider === 'stripe' ? ['#635BFF', '#635BFF'] : [palette.green, palette.green]; return <View style={[styles.providerMark, { backgroundColor: colors[0] }]}><Text style={styles.providerLetter}>{provider === 'paypal' ? 'P' : provider === 'stripe' ? 'S' : '✓'}</Text><View style={[styles.providerAccent, { backgroundColor: colors[1] }]} /></View>; }
function providerDetail(provider: string, amount: number) { if (amount <= 0) return 'No payment is required'; if (provider === 'paypal') return 'Finish securely with PayPal'; if (provider === 'stripe') return 'Credit or debit card via Stripe'; return 'Secure payment provider'; }

const styles = StyleSheet.create({
  backButton: { alignSelf: 'flex-start', minHeight: 40, flexDirection: 'row', alignItems: 'center', gap: 5, borderRadius: 12, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surface, paddingHorizontal: 13 }, backArrow: { color: palette.orange, fontSize: 28, lineHeight: 30, marginTop: -2 }, backText: { color: palette.ink, fontSize: 14, fontWeight: '900' },
  options: { gap: 10 }, option: { minHeight: 76, borderWidth: 1, borderColor: palette.line, borderRadius: 17, backgroundColor: palette.surface, padding: 13, flexDirection: 'row', alignItems: 'center', gap: 12 }, optionSelected: { borderColor: palette.orange, backgroundColor: '#FFF9F5' }, pressed: { opacity: .65 }, optionCopy: { flex: 1 }, optionTitle: { color: palette.ink, fontSize: 15, fontWeight: '900', marginBottom: 2 },
  carBadge: { width: 47, height: 47, borderRadius: 14, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, carBadgeSelected: { backgroundColor: palette.orange }, carLetters: { color: 'white', fontSize: 14, fontWeight: '900' }, carLettersSelected: { color: 'white' },
  radio: { width: 23, height: 23, borderRadius: 12, borderWidth: 2, borderColor: '#D0D5DD', alignItems: 'center', justifyContent: 'center' }, radioSelected: { borderColor: palette.orange }, radioDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: palette.orange },
  providerMark: { width: 47, height: 47, borderRadius: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }, providerLetter: { color: 'white', fontSize: 21, fontWeight: '900', zIndex: 1 }, providerAccent: { position: 'absolute', height: 9, left: 0, right: 0, bottom: 0 },
  addCar: { color: palette.orange, fontWeight: '900' }, summary: { gap: 13 }, summaryRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 14 }, summaryValue: { color: palette.ink, fontWeight: '800', maxWidth: '62%', textAlign: 'right' }, divider: { height: 1, backgroundColor: palette.line }, totalRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }, totalLabel: { color: palette.ink, fontSize: 17, fontWeight: '900' }, total: { color: palette.orange, fontSize: 25, fontWeight: '900' }, capacity: { alignSelf: 'flex-start', color: palette.green, backgroundColor: palette.greenSoft, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 6, fontSize: 11, fontWeight: '900' },
  footnote: { color: palette.muted, textAlign: 'center', fontSize: 11, lineHeight: 17, paddingHorizontal: 18 }, notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800', lineHeight: 20 },
  successCard: { alignItems: 'center', gap: 10, paddingVertical: 28 }, successIcon: { width: 58, height: 58, borderRadius: 29, backgroundColor: palette.green, alignItems: 'center', justifyContent: 'center' }, successTitle: { color: palette.ink, fontSize: 21, fontWeight: '900' }, centerCopy: { color: palette.muted, textAlign: 'center', lineHeight: 20 },
});
