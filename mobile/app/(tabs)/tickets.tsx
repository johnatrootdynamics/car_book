import * as Linking from 'expo-linking';
import { useEffect, useState } from 'react';
import { StyleSheet, Text, View } from 'react-native';
import QRCode from 'react-native-qrcode-svg';
import { Button, Card, Empty, Hero, Loading, Screen, ui } from '@/components/ui';
import { eventDate } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { Ticket } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function TicketsScreen() {
  const { api } = useAuth(); const [tickets, setTickets] = useState<Ticket[] | null>(null);
  useEffect(() => { api<{ tickets: Ticket[] }>('/driver/tickets').then(body => setTickets(body.tickets)).catch(() => setTickets([])); }, [api]);
  if (!tickets) return <Loading />;
  return <Screen><Hero eyebrow="Mobile passes" title="Your tickets" subtitle="Each admission has its own QR code. Turn up the brightness before presenting it." />
    {tickets.length ? tickets.map(ticket => <Card key={ticket.code} style={styles.ticket}><View style={styles.ticketHead}><View style={{ flex: 1 }}><Text style={styles.kind}>{ticket.ticket_type}</Text><Text style={styles.event}>{ticket.event.name}</Text><Text style={ui.body}>{eventDate(ticket.event.date)} · {ticket.event.track.name}</Text></View><View style={[styles.status, ticket.checked_in_at ? styles.used : styles.valid]}><Text style={[styles.statusText, ticket.checked_in_at ? styles.usedText : styles.validText]}>{ticket.checked_in_at ? 'Used' : 'Ready'}</Text></View></View><View style={styles.qr}><QRCode value={ticket.qr_value} size={190} color={palette.ink} backgroundColor="white" /><Text style={styles.code}>{ticket.code}</Text></View>{ticket.wallet.apple || ticket.wallet.google ? <View style={styles.wallets}>{ticket.wallet.apple ? <View style={{ flex: 1 }}><Button tone="secondary" title="Add to Apple Wallet" onPress={() => Linking.openURL(ticket.wallet.apple!)} /></View> : null}{ticket.wallet.google ? <View style={{ flex: 1 }}><Button tone="secondary" title="Add to Google Wallet" onPress={() => Linking.openURL(ticket.wallet.google!)} /></View> : null}</View> : null}</Card>) : <Empty title="No tickets yet" detail="Paid driver and spectator tickets will appear here." />}
  </Screen>;
}
const styles = StyleSheet.create({ ticket: { padding: 0, overflow: 'hidden' }, ticketHead: { padding: 17, flexDirection: 'row', gap: 10 }, kind: { color: palette.orange, fontSize: 12, fontWeight: '900', textTransform: 'uppercase', letterSpacing: 1 }, event: { color: palette.ink, fontSize: 19, fontWeight: '900', marginVertical: 4 }, status: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, alignSelf: 'flex-start' }, valid: { backgroundColor: palette.greenSoft }, used: { backgroundColor: palette.redSoft }, statusText: { fontSize: 12, fontWeight: '900' }, validText: { color: palette.green }, usedText: { color: palette.red }, qr: { borderTopWidth: 1, borderTopColor: palette.line, padding: 22, alignItems: 'center', backgroundColor: '#FCFCFD' }, code: { color: palette.muted, fontSize: 10, marginTop: 10 }, wallets: { flexDirection: 'row', gap: 9, padding: 14, borderTopWidth: 1, borderTopColor: palette.line } });
