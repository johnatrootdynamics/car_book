import { router } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { money } from '@/lib/format';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Order = {
  kind: string;
  kind_label: string;
  id: number;
  number: string;
  event_names: string[];
  buyer_name: string;
  buyer_email: string;
  amount: number;
  provider: string;
  mode: string;
  payment_status: string;
  created_at: string;
};

type Response = { summary: { count: number; paid: number; pending: number; failed: number; paid_total: number }; orders: Order[] };

export default function StaffOrdersScreen() {
  const { api } = useAuth();
  const [data, setData] = useState<Response | null>(null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async (term = '') => {
    setError('');
    try {
      setData(await api<Response>(`/staff/orders?q=${encodeURIComponent(term.trim())}`));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load orders.');
    }
  }, [api]);

  useEffect(() => { load(); }, [load]);
  if (!data && !error) return <Loading />;

  return <Screen>
    <Hero eyebrow="Track commerce" title="Orders" subtitle="Driver, spectator, vendor, and private-rental purchases for your track." />
    {data ? <View style={styles.stats}>
      <Card style={styles.stat}><Text style={styles.statValue}>{data.summary.count}</Text><Text style={styles.statLabel}>Orders</Text></Card>
      <Card style={styles.stat}><Text style={styles.statValue}>{data.summary.paid}</Text><Text style={styles.statLabel}>Paid</Text></Card>
      <Card style={styles.stat}><Text style={styles.statValue}>{money(data.summary.paid_total)}</Text><Text style={styles.statLabel}>Revenue</Text></Card>
    </View> : null}
    <View style={styles.search}><Field style={{ flex: 1 }} value={query} onChangeText={setQuery} onSubmitEditing={() => load(query)} placeholder="Order, buyer, event" autoCapitalize="none" /><View style={{ width: 88 }}><Button title="Find" onPress={() => load(query)} /></View></View>
    {error ? <Text style={styles.error}>{error}</Text> : null}
    <SectionTitle title="Recent orders" />
    {data?.orders.length ? data.orders.map(order => <Pressable key={`${order.kind}-${order.id}`} onPress={() => router.push({ pathname: '/staff/order/[kind]/[id]', params: { kind: order.kind, id: String(order.id) } })}><Card style={styles.order}><View style={styles.top}><View style={styles.copy}><Text style={styles.number}>{order.number}</Text><Text style={styles.buyer}>{order.buyer_name}</Text></View><View style={styles.amountBlock}><Text style={styles.amount}>{money(order.amount)}</Text><Text style={[styles.status, statusStyle(order.payment_status)]}>{order.payment_status}</Text></View></View><Text numberOfLines={2} style={ui.body}>{order.kind_label} · {order.event_names.join(', ')}</Text><View style={styles.footer}><Text style={styles.meta}>{order.provider.toUpperCase()}{order.mode === 'test' ? ' · TEST' : ''}</Text><Text style={styles.meta}>{new Date(order.created_at).toLocaleDateString()}</Text></View></Card></Pressable>) : <Empty title="No orders found" detail="Try a different search or wait for the next purchase." />}
  </Screen>;
}

function statusStyle(status: string) {
  if (status === 'paid') return styles.statusPaid;
  if (status === 'pending') return styles.statusPending;
  return styles.statusFailed;
}

const styles = StyleSheet.create({
  stats: { flexDirection: 'row', gap: 8 },
  stat: { flex: 1, alignItems: 'center', paddingHorizontal: 4 },
  statValue: { color: palette.ink, fontSize: 20, fontWeight: '900' },
  statLabel: { color: palette.muted, fontSize: 11, fontWeight: '700', marginTop: 2 },
  search: { flexDirection: 'row', gap: 9, alignItems: 'center' },
  order: { gap: 8 },
  top: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12 },
  copy: { flex: 1 },
  number: { color: palette.orange, fontSize: 12, fontWeight: '900' },
  buyer: { color: palette.ink, fontSize: 17, fontWeight: '900', marginTop: 3 },
  amountBlock: { alignItems: 'flex-end', gap: 5 },
  amount: { color: palette.ink, fontWeight: '900' },
  status: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4, overflow: 'hidden', fontSize: 10, fontWeight: '900', textTransform: 'uppercase' },
  statusPaid: { color: palette.green, backgroundColor: palette.greenSoft },
  statusPending: { color: '#B54708', backgroundColor: '#FEF0C7' },
  statusFailed: { color: palette.red, backgroundColor: palette.redSoft },
  footer: { flexDirection: 'row', justifyContent: 'space-between', borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 9 },
  meta: { color: palette.muted, fontSize: 11, fontWeight: '700' },
  error: { color: palette.red, fontWeight: '800' },
});
