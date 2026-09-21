import * as Linking from 'expo-linking';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';

import { Button, Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Ticket, TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type TicketGroup = { event: TrackEvent; tickets: Ticket[] };

export default function TicketsScreen() {
  const params = useLocalSearchParams<{ eventId?: string }>();
  const { api } = useAuth();
  const [tickets, setTickets] = useState<Ticket[] | null>(null);
  const [selectedEventId, setSelectedEventId] = useState<number | null>(null);
  const [ticketIndex, setTicketIndex] = useState(0);

  useFocusEffect(useCallback(() => {
    api<{ tickets: Ticket[] }>('/driver/tickets').then(body => setTickets(body.tickets)).catch(() => setTickets([]));
  }, [api]));

  const groups = useMemo<TicketGroup[]>(() => {
    if (!tickets) return [];
    const grouped = new Map<number, TicketGroup>();
    tickets.forEach(ticket => {
      const existing = grouped.get(ticket.event.id);
      if (existing) existing.tickets.push(ticket);
      else grouped.set(ticket.event.id, { event: ticket.event, tickets: [ticket] });
    });
    return [...grouped.values()].sort((a, b) => a.event.date.localeCompare(b.event.date));
  }, [tickets]);

  useEffect(() => {
    if (!groups.length) { setSelectedEventId(null); return; }
    const requested = Number(params.eventId || 0);
    const next = groups.some(group => group.event.id === requested)
      ? requested
      : groups.some(group => group.event.id === selectedEventId)
        ? selectedEventId
        : groups[0].event.id;
    if (next !== selectedEventId) { setSelectedEventId(next); setTicketIndex(0); }
  }, [groups, params.eventId, selectedEventId]);

  if (!tickets) return <Loading />;
  if (!groups.length) return <Screen><Hero eyebrow="Mobile passes" title="Your tickets" subtitle="Current and upcoming event passes will appear here." /><Empty title="No upcoming tickets" detail="Purchase driver or spectator admission from an upcoming event." /></Screen>;

  const group = groups.find(item => item.event.id === selectedEventId) || groups[0];
  const safeIndex = Math.min(ticketIndex, group.tickets.length - 1);
  const ticket = group.tickets[safeIndex];
  const selectEvent = (eventId: number) => { setSelectedEventId(eventId); setTicketIndex(0); };

  return <Screen>
    <Hero eyebrow="Mobile pass" title={group.event.name} subtitle="One QR at a time, ready for fast check-in." />

    {groups.length > 1 ? <>
      <SectionTitle title="Choose event" />
      <View style={styles.eventChoices}>{groups.map(item => <Pressable key={item.event.id} onPress={() => selectEvent(item.event.id)} style={({ pressed }) => [styles.eventChoice, item.event.id === group.event.id && styles.eventChoiceSelected, pressed && styles.pressed]}><Text numberOfLines={1} style={[styles.eventChoiceName, item.event.id === group.event.id && styles.eventChoiceNameSelected]}>{item.event.name}</Text><Text style={[styles.eventChoiceDate, item.event.id === group.event.id && styles.eventChoiceDateSelected]}>{eventDate(item.event.date)}</Text></Pressable>)}</View>
    </> : null}

    <Card style={styles.ticket}>
      <View style={styles.ticketHead}><View style={{ flex: 1 }}><Text style={styles.kind}>{ticket.ticket_type}</Text><Text style={styles.event}>{ticket.event.name}</Text><Text style={ui.body}>{eventDate(ticket.event.date)} · {ticket.event.track.name}</Text></View><View style={[styles.status, ticket.checked_in_at ? styles.used : styles.valid]}><Text style={[styles.statusText, ticket.checked_in_at ? styles.usedText : styles.validText]}>{ticket.checked_in_at ? 'Used' : 'Ready'}</Text></View></View>
      {group.tickets.length > 1 ? <View style={styles.ticketNav}><Pressable disabled={safeIndex === 0} onPress={() => setTicketIndex(index => Math.max(0, index - 1))} style={[styles.navButton, safeIndex === 0 && styles.navDisabled]}><Text style={styles.navText}>‹</Text></Pressable><View style={styles.navCopy}><Text style={styles.navLabel}>TICKET {safeIndex + 1} OF {group.tickets.length}</Text><Text style={styles.navKind}>{ticket.ticket_type}</Text></View><Pressable disabled={safeIndex >= group.tickets.length - 1} onPress={() => setTicketIndex(index => Math.min(group.tickets.length - 1, index + 1))} style={[styles.navButton, safeIndex >= group.tickets.length - 1 && styles.navDisabled]}><Text style={styles.navText}>›</Text></Pressable></View> : null}
      <View style={styles.qr}><QRCode value={ticket.qr_value} size={210} color={palette.ink} backgroundColor="white" /><Text style={styles.code}>{ticket.code}</Text></View>
      {ticket.wallet.apple || ticket.wallet.google ? <View style={styles.wallets}>{ticket.wallet.apple ? <View style={{ flex: 1 }}><Button tone="secondary" title="Apple Wallet" onPress={() => Linking.openURL(ticket.wallet.apple!)} /></View> : null}{ticket.wallet.google ? <View style={{ flex: 1 }}><Button tone="secondary" title="Google Wallet" onPress={() => Linking.openURL(ticket.wallet.google!)} /></View> : null}</View> : null}
    </Card>

    <View style={styles.actions}><View style={{ flex: 1 }}><Button tone="secondary" title="Event details" onPress={() => router.push(`/event/${group.event.id}`)} /></View><View style={{ flex: 1 }}><Button tone="secondary" title="Buy spectators" onPress={() => router.push({ pathname: '/event/[id]/spectator-checkout', params: { id: String(group.event.id) } })} /></View></View>
    <Text style={styles.historyNote}>Past-event QR codes are hidden from this screen.</Text>
  </Screen>;
}

const styles = StyleSheet.create({
  eventChoices: { gap: 8 }, eventChoice: { borderRadius: 14, borderWidth: 1, borderColor: palette.line, backgroundColor: palette.surface, paddingHorizontal: 14, paddingVertical: 11 }, eventChoiceSelected: { borderColor: palette.orange, backgroundColor: palette.orangeSoft }, eventChoiceName: { color: palette.ink, fontWeight: '900' }, eventChoiceNameSelected: { color: '#C2410C' }, eventChoiceDate: { color: palette.muted, fontSize: 11, marginTop: 3 }, eventChoiceDateSelected: { color: '#C2410C' }, pressed: { opacity: .65 },
  ticket: { padding: 0, overflow: 'hidden' }, ticketHead: { padding: 17, flexDirection: 'row', gap: 10 }, kind: { color: palette.orange, fontSize: 12, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1 }, event: { color: palette.ink, fontSize: 19, fontWeight: '900', marginVertical: 4 }, status: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, alignSelf: 'flex-start' }, valid: { backgroundColor: palette.greenSoft }, used: { backgroundColor: palette.redSoft }, statusText: { fontSize: 12, fontWeight: '900' }, validText: { color: palette.green }, usedText: { color: palette.red },
  ticketNav: { borderTopWidth: 1, borderTopColor: palette.line, backgroundColor: '#FCFCFD', padding: 12, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, navButton: { width: 42, height: 42, borderRadius: 13, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', alignItems: 'center', justifyContent: 'center' }, navDisabled: { opacity: .28 }, navText: { color: palette.orange, fontSize: 28, lineHeight: 30 }, navCopy: { alignItems: 'center' }, navLabel: { color: palette.orange, fontSize: 10, fontWeight: '900', letterSpacing: 1 }, navKind: { color: palette.ink, fontSize: 13, fontWeight: '800', marginTop: 2 },
  qr: { borderTopWidth: 1, borderTopColor: palette.line, padding: 24, alignItems: 'center', backgroundColor: 'white' }, code: { color: palette.muted, fontSize: 9, marginTop: 11 }, wallets: { flexDirection: 'row', gap: 9, padding: 14, borderTopWidth: 1, borderTopColor: palette.line }, actions: { flexDirection: 'row', gap: 9 }, historyNote: { color: palette.muted, textAlign: 'center', fontSize: 11 },
});
