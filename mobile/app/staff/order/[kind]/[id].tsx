import { useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type Item = { id?: number; label: string; category?: string; event?: string | null; quantity?: number; amount?: number; checked_in_at?: string | null; date?: string; car?: Car };
type Order = { kind: string; kind_label: string; id: number; number: string; event_names: string[]; buyer_name: string; buyer_email: string; amount: number; provider: string; mode: string; payment_status: string; transaction_id?: string | null; created_at: string; paid_at?: string | null; items: Item[] };

export default function StaffOrderDetailScreen() {
  const { kind, id } = useLocalSearchParams<{ kind: string; id: string }>();
  const { api } = useAuth();
  const [order, setOrder] = useState<Order | null>(null);
  const [message, setMessage] = useState('');
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    try {
      const body = await api<{ order: Order }>(`/staff/orders/${kind}/${id}`);
      setOrder(body.order);
    } catch (caught) {
      setMessage(caught instanceof Error ? caught.message : 'Unable to load this order.');
    }
  }, [api, id, kind]);
  useEffect(() => { load(); }, [load]);

  const resend = () => Alert.alert('Resend confirmation?', `TrackOps will email the tickets or confirmation to ${order?.buyer_email || 'the purchaser'}.`, [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Resend', onPress: async () => {
      setBusy(true); setMessage('');
      try {
        const body = await api<{ message: string }>(`/staff/orders/${kind}/${id}/resend`, { method: 'POST' });
        setMessage(body.message);
      } catch (caught) {
        setMessage(caught instanceof Error ? caught.message : 'Unable to resend the email.');
      } finally { setBusy(false); }
    } },
  ]);

  if (!order) return message ? <Screen><Empty title="Order unavailable" detail={message} /></Screen> : <Loading />;
  return <Screen>
    <Hero eyebrow={order.kind_label} title={order.number} subtitle={order.event_names.join(' · ')} />
    <Card>
      <Detail label="Buyer" value={order.buyer_name} />
      {order.buyer_email ? <Detail label="Email" value={order.buyer_email} /> : null}
      <Detail label="Total" value={money(order.amount)} />
      <Detail label="Payment" value={order.payment_status} />
      <Detail label="Provider" value={`${order.provider}${order.mode === 'test' ? ' · test mode' : ''}`} />
      <Detail label="Ordered" value={new Date(order.created_at).toLocaleString()} />
      {order.transaction_id ? <Detail label="Transaction" value={order.transaction_id} /> : null}
    </Card>
    {message ? <Text style={styles.message}>{message}</Text> : null}
    <SectionTitle title="Order items" />
    {order.items.map((item, index) => <Card key={item.id || index}><View style={ui.between}><View style={styles.itemCopy}><Text style={ui.title}>{item.label}</Text><Text style={ui.body}>{item.event || item.date}{item.car ? ` · ${item.car.label}` : ''}</Text></View>{item.amount !== undefined ? <Text style={styles.amount}>{money(item.amount)}</Text> : null}</View>{item.quantity ? <Text style={styles.meta}>Quantity {item.quantity}</Text> : null}{item.checked_in_at ? <Text style={styles.checked}>Checked in {new Date(item.checked_in_at).toLocaleString()}</Text> : null}</Card>)}
    <Button title={busy ? 'Sending…' : 'Resend confirmation email'} disabled={busy || order.payment_status !== 'paid' || !order.buyer_email} onPress={resend} />
    {order.payment_status !== 'paid' ? <Text style={styles.help}>Email is available after payment is confirmed.</Text> : null}
  </Screen>;
}

function Detail({ label, value }: { label: string; value: string }) {
  return <View style={styles.detail}><Text style={ui.body}>{label}</Text><Text style={styles.value}>{value}</Text></View>;
}

const styles = StyleSheet.create({
  detail: { borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 11, marginTop: 11 },
  value: { color: palette.ink, fontSize: 15, fontWeight: '800', marginTop: 3 },
  itemCopy: { flex: 1, paddingRight: 10 },
  amount: { color: palette.ink, fontWeight: '900' },
  meta: { color: palette.muted, fontSize: 12, marginTop: 9 },
  checked: { color: palette.green, fontSize: 12, fontWeight: '800', marginTop: 9 },
  message: { color: palette.green, fontWeight: '800' },
  help: { color: palette.muted, textAlign: 'center', fontSize: 12 },
});
