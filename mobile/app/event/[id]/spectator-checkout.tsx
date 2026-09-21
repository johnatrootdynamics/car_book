import * as WebBrowser from 'expo-web-browser';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type TicketType = {
  id: number;
  name: string;
  price: number;
  max_per_order: number;
  availability: { remaining: number | null; unlimited: boolean; sold_out: boolean };
};
type PaymentMethod = { provider: string; label: string };
type CheckoutData = {
  event: TrackEvent;
  ticket_types: TicketType[];
  payment_methods: PaymentMethod[];
  buyer: { name: string; email: string };
};
type Order = {
  id: number;
  number: string;
  event_id: number;
  amount: number;
  ticket_count: number;
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

export default function SpectatorCheckoutScreen() {
  const params = useLocalSearchParams<{ id: string; checkout_status?: string; order_id?: string }>();
  const eventId = Number(params.id);
  const { account, api } = useAuth();
  const [data, setData] = useState<CheckoutData | null>(null);
  const [ticketTypeId, setTicketTypeId] = useState<number | null>(null);
  const [quantity, setQuantity] = useState(1);
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
      const body = await api<CheckoutData>(`/driver/events/${eventId}/spectator-checkout`);
      setData(body);
      const firstAvailable = body.ticket_types.find(item => item.max_per_order > 0);
      setTicketTypeId(current => current && body.ticket_types.some(item => item.id === current && item.max_per_order > 0) ? current : firstAvailable?.id || null);
      setProvider(current => current && body.payment_methods.some(method => method.provider === current) ? current : body.payment_methods[0]?.provider || '');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to prepare spectator checkout.');
    } finally { setLoading(false); }
  }, [account, api, eventId]);

  const refreshOrder = useCallback(async (orderId: number) => {
    const body = await api<{ order: Order }>(`/driver/spectator-orders/${orderId}`);
    setOrder(body.order);
    if (body.order.payment_status === 'paid') {
      setNotice('Payment confirmed. Every spectator ticket now has its own QR code.');
      setError('');
    } else if (body.order.payment_status === 'failed') {
      setError(body.order.failure_reason || 'The payment could not be completed.');
    } else if (body.order.payment_status === 'canceled') {
      setNotice('Checkout was canceled. You can start again when ready.');
    } else {
      setNotice('Payment is still processing. Tickets appear only after confirmation.');
    }
    return body.order;
  }, [api]);

  useFocusEffect(useCallback(() => { load(); }, [load]));
  useEffect(() => {
    const returnedOrderId = Number(params.order_id || 0);
    if (!returnedOrderId) return;
    refreshOrder(returnedOrderId).catch(caught => setError(caught instanceof Error ? caught.message : 'Unable to check payment status.'));
  }, [params.checkout_status, params.order_id, refreshOrder]);

  const selectedType = data?.ticket_types.find(item => item.id === ticketTypeId);
  const maxQuantity = selectedType?.max_per_order || 1;
  useEffect(() => { setQuantity(current => Math.max(1, Math.min(current, maxQuantity))); }, [maxQuantity]);
  const total = useMemo(() => (selectedType?.price || 0) * quantity, [quantity, selectedType?.price]);
  const selectedMethod = data?.payment_methods.find(method => method.provider === provider);

  const purchase = async () => {
    if (!ticketTypeId || !provider || !selectedType) return;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await api<CheckoutResponse>(`/driver/events/${eventId}/spectator-checkout`, {
        method: 'POST',
        body: JSON.stringify({ ticket_type_id: ticketTypeId, quantity, payment_method: provider }),
      });
      setOrder(result.order);
      if (result.completed) {
        setNotice('Your spectator tickets and QR codes are ready.');
        return;
      }
      if (!result.checkout_url) throw new Error('The payment provider did not return a checkout link.');
      const browserResult = await WebBrowser.openAuthSessionAsync(result.checkout_url, result.return_url);
      if (browserResult.type === 'success') await refreshOrder(result.order.id);
      else setNotice('No payment was completed. You can resume checkout when ready.');
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to start checkout.');
    } finally { setBusy(false); }
  };

  if (account?.type !== 'user') return <Screen><Empty title="Driver account required" detail="Sign in as a driver to purchase spectator tickets." /></Screen>;
  if (loading && !data && !order) return <Loading />;
  if (order?.payment_status === 'paid') return <Screen>
    <Hero eyebrow="Payment confirmed" title={`${order.ticket_count} spectator ticket${order.ticket_count === 1 ? '' : 's'} ready`} subtitle="Each guest has a separate QR code for admission." />
    <Card style={styles.successCard}><View style={styles.successIcon}><SymbolView name={{ ios: 'checkmark', android: 'checkmark', web: 'checkmark' } as any} tintColor="white" size={28} /></View><Text style={styles.successTitle}>Order {order.number}</Text><Text style={styles.centerCopy}>The tickets were emailed to you and are available one at a time in the Tickets tab.</Text></Card>
    <Button title="View tickets for this event" onPress={() => router.replace({ pathname: '/(tabs)/tickets', params: { eventId: String(eventId) } })} />
    <Button tone="secondary" title="Back to event" onPress={() => router.replace(`/event/${eventId}`)} />
  </Screen>;
  if (!data) return <Screen><BackButton eventId={eventId} /><Empty title="Spectator checkout unavailable" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={load} /></Screen>;

  return <Screen>
    <BackButton eventId={eventId} />
    <Hero eyebrow="Spectator admission" title={data.event.name} subtitle={`${eventDate(data.event.date)} · ${data.event.track.name}`} />
    {notice ? <Notice tone="success" text={notice} /> : null}
    {error ? <Notice tone="error" text={error} /> : null}

    <SectionTitle title="Choose admission" />
    <View style={styles.options}>{data.ticket_types.map(ticket => <Pressable key={ticket.id} disabled={ticket.max_per_order <= 0} onPress={() => setTicketTypeId(ticket.id)} style={({ pressed }) => [styles.option, ticketTypeId === ticket.id && styles.optionSelected, ticket.max_per_order <= 0 && styles.disabled, pressed && styles.pressed]}><View style={styles.ticketBadge}><SymbolView name={{ ios: 'person.2.fill', android: 'person.2.fill', web: 'person.2.fill' } as any} tintColor={palette.orange} size={22} /></View><View style={styles.optionCopy}><Text style={styles.optionTitle}>{ticket.name}</Text><Text style={ui.body}>{money(ticket.price)} each · {ticket.availability.unlimited ? `Up to ${ticket.max_per_order}` : `${ticket.availability.remaining ?? 0} left`}</Text></View><Selection selected={ticketTypeId === ticket.id} /></Pressable>)}</View>

    <SectionTitle title="How many?" />
    <Card style={styles.quantityCard}><Pressable accessibilityLabel="Remove one ticket" disabled={quantity <= 1} onPress={() => setQuantity(value => Math.max(1, value - 1))} style={[styles.quantityButton, quantity <= 1 && styles.disabled]}><Text style={styles.quantitySymbol}>−</Text></Pressable><View style={styles.quantityCopy}><Text style={styles.quantity}>{quantity}</Text><Text style={styles.quantityLabel}>ticket{quantity === 1 ? '' : 's'}</Text></View><Pressable accessibilityLabel="Add one ticket" disabled={quantity >= maxQuantity} onPress={() => setQuantity(value => Math.min(maxQuantity, value + 1))} style={[styles.quantityButton, quantity >= maxQuantity && styles.disabled]}><Text style={styles.quantitySymbol}>+</Text></Pressable></Card>

    <SectionTitle title="Payment method" />
    {data.payment_methods.length ? <View style={styles.options}>{data.payment_methods.map(method => <Pressable key={method.provider} onPress={() => setProvider(method.provider)} style={({ pressed }) => [styles.option, provider === method.provider && styles.optionSelected, pressed && styles.pressed]}><ProviderMark provider={method.provider} /><View style={styles.optionCopy}><Text style={styles.optionTitle}>{method.label}</Text><Text style={ui.body}>{providerDetail(method.provider, total)}</Text></View><Selection selected={provider === method.provider} /></Pressable>)}</View> : <Empty title="Payment is not configured" detail="This track has not enabled a payment method for spectator admission yet." />}

    <SectionTitle title="Order summary" />
    <Card style={styles.summary}><View style={styles.summaryRow}><Text style={ui.body}>{selectedType?.name || 'Spectator admission'} × {quantity}</Text><Text style={styles.summaryValue}>{money(total)}</Text></View><View style={styles.summaryRow}><Text style={ui.body}>Purchaser</Text><Text style={styles.summaryValue}>{data.buyer.name}</Text></View><View style={styles.divider} /><View style={styles.totalRow}><Text style={styles.totalLabel}>Total</Text><Text style={styles.total}>{money(total)}</Text></View></Card>
    <Button title={busy ? 'Opening secure checkout…' : total <= 0 ? 'Confirm free spectator tickets' : `Pay ${money(total)} with ${selectedMethod?.label || 'provider'}`} onPress={purchase} disabled={busy || !ticketTypeId || !provider || !data.payment_methods.length || maxQuantity <= 0} />
    <Text style={styles.footnote}>Every spectator receives a separate QR code. Tickets are issued only after payment is confirmed.</Text>
  </Screen>;
}

function BackButton({ eventId }: { eventId: number }) { return <Pressable accessibilityRole="button" onPress={() => router.canGoBack() ? router.back() : router.replace(`/event/${eventId}`)} style={({ pressed }) => [styles.backButton, pressed && styles.pressed]}><Text style={styles.backArrow}>‹</Text><Text style={styles.backText}>Event</Text></Pressable>; }
function Selection({ selected }: { selected: boolean }) { return <View style={[styles.radio, selected && styles.radioSelected]}>{selected ? <View style={styles.radioDot} /> : null}</View>; }
function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: tone === 'success' ? palette.green : palette.red }]}>{text}</Text></View>; }
function ProviderMark({ provider }: { provider: string }) { const colors = provider === 'paypal' ? ['#003087', '#009CDE'] : provider === 'stripe' ? ['#635BFF', '#635BFF'] : [palette.green, palette.green]; return <View style={[styles.providerMark, { backgroundColor: colors[0] }]}><Text style={styles.providerLetter}>{provider === 'paypal' ? 'P' : provider === 'stripe' ? 'S' : '✓'}</Text><View style={[styles.providerAccent, { backgroundColor: colors[1] }]} /></View>; }
function providerDetail(provider: string, amount: number) { if (amount <= 0) return 'No payment is required'; if (provider === 'paypal') return 'Finish securely with PayPal'; if (provider === 'stripe') return 'Credit or debit card via Stripe'; return 'Secure payment provider'; }

const styles = StyleSheet.create({
  backButton: { alignSelf: 'flex-start', minHeight: 40, flexDirection: 'row', alignItems: 'center', gap: 5, borderRadius: 12, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surface, paddingHorizontal: 13 }, backArrow: { color: palette.orange, fontSize: 28, lineHeight: 30, marginTop: -2 }, backText: { color: palette.ink, fontSize: 14, fontWeight: '900' },
  options: { gap: 10 }, option: { minHeight: 76, borderWidth: 1, borderColor: palette.line, borderRadius: 17, backgroundColor: palette.surface, padding: 13, flexDirection: 'row', alignItems: 'center', gap: 12 }, optionSelected: { borderColor: palette.orange, backgroundColor: '#FFF9F5' }, optionCopy: { flex: 1 }, optionTitle: { color: palette.ink, fontSize: 15, fontWeight: '900', marginBottom: 2 }, pressed: { opacity: .65 }, disabled: { opacity: .4 },
  ticketBadge: { width: 47, height: 47, borderRadius: 14, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, radio: { width: 23, height: 23, borderRadius: 12, borderWidth: 2, borderColor: '#D0D5DD', alignItems: 'center', justifyContent: 'center' }, radioSelected: { borderColor: palette.orange }, radioDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: palette.orange },
  quantityCard: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, quantityButton: { width: 54, height: 54, borderRadius: 16, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, quantitySymbol: { color: palette.orange, fontSize: 30, fontWeight: '800' }, quantityCopy: { alignItems: 'center' }, quantity: { color: palette.ink, fontSize: 28, fontWeight: '900' }, quantityLabel: { color: palette.muted, fontSize: 11, fontWeight: '800' },
  providerMark: { width: 47, height: 47, borderRadius: 14, alignItems: 'center', justifyContent: 'center', overflow: 'hidden' }, providerLetter: { color: 'white', fontSize: 21, fontWeight: '900', zIndex: 1 }, providerAccent: { position: 'absolute', height: 9, left: 0, right: 0, bottom: 0 },
  summary: { gap: 13 }, summaryRow: { flexDirection: 'row', justifyContent: 'space-between', gap: 14 }, summaryValue: { color: palette.ink, fontWeight: '800', maxWidth: '62%', textAlign: 'right' }, divider: { height: 1, backgroundColor: palette.line }, totalRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'baseline' }, totalLabel: { color: palette.ink, fontSize: 17, fontWeight: '900' }, total: { color: palette.orange, fontSize: 25, fontWeight: '900' }, footnote: { color: palette.muted, textAlign: 'center', fontSize: 11, lineHeight: 17, paddingHorizontal: 18 },
  notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800', lineHeight: 20 }, successCard: { alignItems: 'center', gap: 10, paddingVertical: 28 }, successIcon: { width: 58, height: 58, borderRadius: 29, backgroundColor: palette.green, alignItems: 'center', justifyContent: 'center' }, successTitle: { color: palette.ink, fontSize: 21, fontWeight: '900' }, centerCopy: { color: palette.muted, textAlign: 'center', lineHeight: 20 },
});
