import { useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type InventoryTag = { id: number; serial: string; epc: string; tid?: string | null; status: string; car?: Car | null; created_at: string };
type OrderItem = { id: number; car: Car; unit_price: number; tag?: { id: number; serial: string; status: string } | null };
type Order = { id: number; number: string; amount: number; payment_status: string; fulfillment_status: string; created_at: string; fulfilled_at?: string | null; shipping: { name: string; street: string; city: string; state: string; postal_code: string }; items: OrderItem[] };
type AdminRfid = { unit_price: number; inventory: InventoryTag[]; orders: Order[]; message?: string; issued_tag?: { id: number; serial: string; activation_code: string } };
type OrderDetail = { order: Order; available_tags: { id: number; serial: string; epc: string }[] };

export default function AdminRfidScreen() {
  const { account, api } = useAuth();
  const [data, setData] = useState<AdminRfid | null>(null);
  const [price, setPrice] = useState('');
  const [epc, setEpc] = useState('');
  const [tid, setTid] = useState('');
  const [issued, setIssued] = useState<AdminRfid['issued_tag']>();
  const [detail, setDetail] = useState<OrderDetail | null>(null);
  const [assignments, setAssignments] = useState<Record<string, number>>({});
  const [busy, setBusy] = useState('');
  const [notice, setNotice] = useState('');
  const [error, setError] = useState('');

  const load = useCallback(async () => {
    setError('');
    try {
      const body = await api<AdminRfid>('/admin/rfid');
      setData(body); setPrice(body.unit_price.toFixed(2));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to load RFID fulfillment.');
    }
  }, [api]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const savePrice = async () => {
    setBusy('price'); setError(''); setNotice('');
    try {
      const body = await api<AdminRfid>('/admin/rfid/settings', { method: 'PUT', body: JSON.stringify({ unit_price: price }) });
      setData(body); setPrice(body.unit_price.toFixed(2)); setNotice(body.message || 'RFID price saved.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to save the tag price.'); }
    finally { setBusy(''); }
  };

  const provision = async () => {
    setBusy('provision'); setError(''); setNotice(''); setIssued(undefined);
    try {
      const body = await api<AdminRfid>('/admin/rfid/inventory', { method: 'POST', body: JSON.stringify({ epc, tid }) });
      setData(body); setIssued(body.issued_tag); setEpc(''); setTid(''); setNotice(body.message || 'Tag provisioned.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to provision the tag.'); }
    finally { setBusy(''); }
  };

  const openOrder = async (orderId: number) => {
    if (detail?.order.id === orderId) { setDetail(null); setAssignments({}); return; }
    setBusy(`order-${orderId}`); setError('');
    try {
      const body = await api<OrderDetail>(`/admin/rfid/orders/${orderId}`);
      setDetail(body);
      setAssignments(Object.fromEntries(body.order.items.filter(item => item.tag).map(item => [String(item.id), item.tag!.id])));
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to load that order.'); }
    finally { setBusy(''); }
  };

  const fulfill = async () => {
    if (!detail) return;
    setBusy('fulfill'); setError(''); setNotice('');
    try {
      const body = await api<AdminRfid>(`/admin/rfid/orders/${detail.order.id}/fulfill`, { method: 'POST', body: JSON.stringify({ assignments }) });
      setData(body); setDetail(null); setAssignments({}); setNotice(body.message || 'Order fulfilled.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to fulfill that order.'); }
    finally { setBusy(''); }
  };

  if (account?.type !== 'admin') return <Screen><Empty title="Enterprise admin required" detail="Only enterprise admins can provision and fulfill RFID tags." /></Screen>;
  if (!data && !error) return <Loading />;
  if (!data) return <Screen><Empty title="RFID fulfillment unavailable" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={load} /></Screen>;

  const unassignedCount = data.inventory.filter(tag => tag.status === 'inventory' && !tag.car).length;
  const pendingCount = data.orders.filter(order => order.payment_status === 'paid' && order.fulfillment_status !== 'fulfilled').length;
  return <Screen>
    <Hero eyebrow="Enterprise fulfillment" title="RFID operations" subtitle="Provision physical tags, set the store price, and fulfill paid driver orders." />
    {notice ? <Notice tone="success" text={notice} /> : null}
    {error ? <Notice tone="error" text={error} /> : null}

    <View style={styles.stats}><Card style={styles.stat}><Text style={styles.statValue}>{unassignedCount}</Text><Text style={styles.statLabel}>Available tags</Text></Card><Card style={styles.stat}><Text style={styles.statValue}>{pendingCount}</Text><Text style={styles.statLabel}>Ready to fulfill</Text></Card></View>

    {issued ? <Card style={styles.secretCard}><View style={ui.between}><Text style={styles.secretTitle}>Save this activation label</Text><Status text="Shown once" good={false} /></View><Text style={ui.body}>Include this serial and private code with the physical tag.</Text><View style={styles.secretGrid}><View><Text style={styles.secretLabel}>Serial</Text><Text selectable style={styles.secretValue}>{issued.serial}</Text></View><View><Text style={styles.secretLabel}>Activation code</Text><Text selectable style={styles.secretValue}>{issued.activation_code}</Text></View></View></Card> : null}

    <SectionTitle title="Provision inventory" />
    <Card style={styles.form}>
      <View><Text style={ui.label}>EPC</Text><Field autoCapitalize="characters" autoCorrect={false} placeholder="Encoded tag EPC" value={epc} onChangeText={setEpc} /></View>
      <View><Text style={ui.label}>TID (optional)</Text><Field autoCapitalize="characters" autoCorrect={false} placeholder="Manufacturer tag ID" value={tid} onChangeText={setTid} /></View>
      <Button title={busy === 'provision' ? 'Provisioning…' : 'Provision tag'} disabled={busy !== '' || !epc.trim()} onPress={provision} />
    </Card>

    <SectionTitle title="Store price" />
    <Card style={styles.priceCard}><View style={styles.grow}><Text style={ui.label}>Price per physical tag (USD)</Text><Field keyboardType="decimal-pad" value={price} onChangeText={setPrice} /></View><View style={styles.savePrice}><Button title={busy === 'price' ? 'Saving…' : 'Save'} disabled={busy !== '' || !price.trim()} onPress={savePrice} /></View></Card>

    <SectionTitle title="Fulfillment orders" />
    {data.orders.length ? <View style={styles.stack}>{data.orders.map(order => <View key={order.id}>
      <Pressable onPress={() => openOrder(order.id)} style={({ pressed }) => [styles.orderRow, detail?.order.id === order.id && styles.orderRowOpen, pressed && styles.pressed]}>
        <View style={styles.grow}><Text style={styles.rowTitle}>{order.number}</Text><Text style={ui.body}>{order.shipping.name} · {order.items.length} tag{order.items.length === 1 ? '' : 's'} · {money(order.amount)}</Text></View>
        <Status text={order.fulfillment_status === 'fulfilled' ? 'Fulfilled' : order.payment_status === 'paid' ? 'Ready' : titleCase(order.payment_status)} good={order.payment_status === 'paid'} />
        <Text style={styles.arrow}>{busy === `order-${order.id}` ? '…' : detail?.order.id === order.id ? '⌃' : '›'}</Text>
      </Pressable>
      {detail?.order.id === order.id ? <Card style={styles.fulfillCard}>
        <View><Text style={styles.rowTitle}>Ship to</Text><Text style={ui.body}>{order.shipping.name}{'\n'}{order.shipping.street}{'\n'}{order.shipping.city}, {order.shipping.state} {order.shipping.postal_code}</Text></View>
        {order.fulfillment_status === 'fulfilled' ? <>{order.items.map(item => <View key={item.id} style={styles.assignedRow}><View><Text style={styles.rowTitle}>{item.car.label}</Text><Text style={ui.body}>{item.tag?.serial || 'Assigned tag'}</Text></View><Status text="Assigned" good /></View>)}</> : <>
          <Text style={ui.body}>Choose a different inventory tag for each vehicle. The driver receives fresh activation codes by email.</Text>
          {order.items.map(item => <View key={item.id} style={styles.assignment}><Text style={styles.rowTitle}>{item.car.label}</Text><View style={styles.tags}>{detail.available_tags.map(tag => {
            const selected = assignments[String(item.id)] === tag.id;
            const usedElsewhere = Object.entries(assignments).some(([itemId, tagId]) => itemId !== String(item.id) && tagId === tag.id);
            return <Pressable key={tag.id} disabled={usedElsewhere} onPress={() => setAssignments(current => ({ ...current, [String(item.id)]: tag.id }))} style={[styles.tagChoice, selected && styles.tagChoiceActive, usedElsewhere && styles.tagChoiceDisabled]}><Text style={[styles.tagChoiceText, selected && styles.tagChoiceTextActive]}>{tag.serial}</Text><Text style={[styles.tagEpc, selected && styles.tagChoiceTextActive]} numberOfLines={1}>{tag.epc}</Text></Pressable>;
          })}</View></View>)}
          {!detail.available_tags.length ? <Text style={styles.errorText}>Provision inventory before fulfilling this order.</Text> : null}
          <Button title={busy === 'fulfill' ? 'Sending activation email…' : 'Fulfill and email driver'} disabled={busy !== '' || order.payment_status !== 'paid' || order.items.some(item => !assignments[String(item.id)])} onPress={fulfill} />
        </>}
      </Card> : null}
    </View>)}</View> : <Empty title="No RFID orders" detail="Paid driver tag orders will appear here for fulfillment." />}

    <SectionTitle title="Recent inventory" />
    {data.inventory.length ? <Card style={styles.inventoryList}>{data.inventory.slice(0, 30).map((tag, index) => <View key={tag.id} style={[styles.inventoryRow, index > 0 && styles.divider]}><View style={styles.grow}><Text style={styles.rowTitle}>{tag.serial}</Text><Text style={styles.epc} numberOfLines={1}>{tag.epc}</Text></View><Status text={tag.car ? 'Active' : titleCase(tag.status)} good={tag.status === 'active'} /></View>)}</Card> : <Empty title="No tags provisioned" detail="Provision the first physical RFID tag above." />}
  </Screen>;
}

function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: tone === 'success' ? palette.green : palette.red }]}>{text}</Text></View>; }
function Status({ text, good }: { text: string; good: boolean }) { return <Text style={[styles.status, good ? styles.goodStatus : styles.waitStatus]}>{text}</Text>; }
function money(value: number) { return new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD' }).format(value || 0); }
function titleCase(value: string) { return value.replace(/_/g, ' ').replace(/\b\w/g, letter => letter.toUpperCase()); }

const styles = StyleSheet.create({
  grow: { flex: 1 }, pressed: { opacity: .65 }, stack: { gap: 9 }, stats: { flexDirection: 'row', gap: 10 }, stat: { flex: 1, gap: 3 }, statValue: { color: palette.navy, fontSize: 28, fontWeight: '900' }, statLabel: { color: palette.muted, fontSize: 12, fontWeight: '700' },
  form: { gap: 13 }, priceCard: { flexDirection: 'row', alignItems: 'flex-end', gap: 10 }, savePrice: { width: 92 },
  secretCard: { gap: 12, borderColor: '#F79009', backgroundColor: '#FFFAEB' }, secretTitle: { color: palette.ink, fontSize: 17, fontWeight: '900' }, secretGrid: { gap: 12 }, secretLabel: { color: palette.muted, fontSize: 11, fontWeight: '800', textTransform: 'uppercase', letterSpacing: .8 }, secretValue: { color: palette.ink, fontSize: 20, fontWeight: '900', marginTop: 3 },
  orderRow: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 10, borderWidth: 1, borderColor: palette.line, borderRadius: 17, backgroundColor: 'white', padding: 13 }, orderRowOpen: { borderColor: palette.orange, borderBottomLeftRadius: 6, borderBottomRightRadius: 6 }, rowTitle: { color: palette.ink, fontSize: 15, fontWeight: '900' }, arrow: { color: palette.orange, fontSize: 25, width: 17, textAlign: 'center' },
  fulfillCard: { marginTop: 6, gap: 15, borderTopLeftRadius: 6, borderTopRightRadius: 6 }, assignment: { gap: 8 }, tags: { gap: 7 }, tagChoice: { borderWidth: 1, borderColor: palette.line, borderRadius: 12, paddingHorizontal: 11, paddingVertical: 9, backgroundColor: 'white' }, tagChoiceActive: { borderColor: palette.navy, backgroundColor: palette.navy }, tagChoiceDisabled: { opacity: .35 }, tagChoiceText: { color: palette.ink, fontWeight: '900' }, tagChoiceTextActive: { color: 'white' }, tagEpc: { color: palette.muted, fontSize: 10, marginTop: 2 }, assignedRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10, paddingVertical: 8 },
  inventoryList: { paddingVertical: 2 }, inventoryRow: { minHeight: 65, flexDirection: 'row', alignItems: 'center', gap: 10, paddingVertical: 10 }, divider: { borderTopWidth: 1, borderTopColor: palette.line }, epc: { color: palette.muted, fontFamily: 'Menlo', fontSize: 11, marginTop: 3 },
  status: { overflow: 'hidden', paddingHorizontal: 9, paddingVertical: 5, borderRadius: 999, fontSize: 10, fontWeight: '900' }, goodStatus: { color: palette.green, backgroundColor: palette.greenSoft }, waitStatus: { color: '#B54708', backgroundColor: '#FFFAEB' }, notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800', lineHeight: 20 }, errorText: { color: palette.red, fontWeight: '800', textAlign: 'center' },
});
