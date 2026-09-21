import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { SymbolView } from 'expo-symbols';
import { useCallback, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Card, Empty, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import type { TrackEvent } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

type Detail = TrackEvent & {
  registration?: { checked_in_at: string | null; ticket_code: string; car: { label: string } } | null;
  vendors?: { id: number | null; business_name: string; website?: string; logo_url?: string }[];
  registration_count?: number;
  checked_in_count?: number;
};

type EventTool = {
  title: string;
  detail: string;
  symbol: string;
  action?: 'general' | 'participants' | 'schedule' | 'lanes' | 'live' | 'history' | 'analytics';
  native?: 'scanner';
};

export default function EventDetailScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { account, api } = useAuth();
  const [event, setEvent] = useState<Detail | null>(null);
  const [failed, setFailed] = useState(false);

  useFocusEffect(useCallback(() => {
    if (!account || !['user', 'employee'].includes(account.type)) {
      setFailed(true);
      return;
    }
    const path = account.type === 'employee' ? `/staff/events/${id}` : `/driver/events/${id}`;
    api<{ event: Detail }>(path).then(body => setEvent(body.event)).catch(() => setFailed(true));
  }, [account, api, id]));

  if (!event && !failed) return <Loading />;
  if (!event) return <Screen><Empty title="Event unavailable" detail="This event is not available to your account." /></Screen>;

  const tools: EventTool[] = account?.type === 'employee' ? [
    ...(account.role === 'office_staff' ? [
      { title: 'General & pricing', detail: 'Event details, capacity, tickets, layout, and voting', symbol: 'slider.horizontal.3', action: 'general' as const },
    ] : []),
    { title: 'Check in & inspect', detail: 'Scan tickets, find drivers, and complete inspections', symbol: 'qrcode.viewfinder', native: 'scanner' },
    { title: 'Participants', detail: 'Drivers, cars, classes, waivers, and status', symbol: 'person.2.fill', action: 'participants' },
    { title: 'Schedule', detail: 'Run times and class slots for this event', symbol: 'clock.fill', action: 'schedule' },
    { title: 'Lineup lanes', detail: 'Staging lanes and driver instructions', symbol: 'signpost.right.fill', action: 'lanes' },
    { title: 'Live track', detail: 'Current sessions, run groups, and timing', symbol: 'flag.checkered', action: 'live' },
    { title: 'Run history', detail: 'Completed sessions, participants, votes, and video', symbol: 'clock.arrow.circlepath', action: 'history' },
    ...(account.role === 'office_staff' ? [
      { title: 'Analytics', detail: 'Registration trends and class distribution', symbol: 'chart.bar.fill', action: 'analytics' as const },
    ] : []),
  ] : [];

  const openTool = (tool: EventTool) => {
    if (tool.native === 'scanner') {
      router.push({ pathname: '/(tabs)/scanner', params: { eventId: String(event.id), eventName: event.name } });
      return;
    }
    if (!tool.action) return;
    router.push({ pathname: '/event-tools/[id]/[action]', params: { id: String(event.id), action: tool.action } });
  };

  return <Screen>
    <Hero eyebrow={event.type === 'private' ? 'Private rental' : event.track.name} title={event.name} subtitle={`${eventDate(event.date)} · ${event.track.location}`} />
    <Card>
      <Text style={ui.title}>Event details</Text>
      <View style={styles.line}><Text style={ui.body}>Driver admission</Text><Text style={styles.value}>{money(event.prices.driver)}</Text></View>
      <View style={styles.line}><Text style={ui.body}>Capacity</Text><Text style={styles.value}>{event.availability?.driver?.unlimited ? 'Open' : `${event.availability?.driver?.remaining ?? 0} left`}</Text></View>
      {event.registration_count !== undefined ? <>
        <View style={styles.line}><Text style={ui.body}>Drivers registered</Text><Text style={styles.value}>{event.registration_count}</Text></View>
        <View style={styles.line}><Text style={ui.body}>Checked in</Text><Text style={styles.value}>{event.checked_in_count}</Text></View>
      </> : null}
      {event.registration ? <View style={styles.booked}><Text style={styles.bookedTitle}>You’re registered</Text><Text style={styles.bookedText}>{event.registration.car.label}{event.registration.checked_in_at ? ' · Checked in' : ''}</Text></View> : null}
    </Card>

    {account?.type === 'employee' ? <>
      <SectionTitle title="Event operations" />
      <Card style={styles.toolList}>
        {tools.map((tool, index) => <Pressable key={tool.title} onPress={() => openTool(tool)} style={({ pressed }) => [styles.toolRow, index > 0 && styles.toolDivider, pressed && styles.pressed]}>
          <View style={styles.toolIcon}><SymbolView name={{ ios: tool.symbol, android: tool.symbol, web: tool.symbol } as any} tintColor={palette.orange} size={21} /></View>
          <View style={styles.toolCopy}><Text style={styles.toolTitle}>{tool.title}</Text><Text style={ui.body}>{tool.detail}</Text></View>
          <Text style={styles.arrow}>›</Text>
        </Pressable>)}
      </Card>
    </> : null}

    {account?.type === 'user' ? <>
      {event.type === 'public' ? <>
        <SectionTitle title="Tickets" />
        <Card style={styles.ticketMenu}>
          <Pressable disabled={!!event.registration || !!event.availability?.driver?.sold_out} onPress={() => router.push({ pathname: '/event/[id]/checkout', params: { id: String(event.id) } })} style={({ pressed }) => [styles.ticketRow, pressed && styles.pressed, (event.registration || event.availability?.driver?.sold_out) && styles.ticketDisabled]}>
            <View style={styles.ticketIcon}><SymbolView name={{ ios: 'car.fill', android: 'car.fill', web: 'car.fill' } as any} tintColor={palette.orange} size={22} /></View><View style={styles.ticketCopy}><Text style={styles.ticketTitle}>Driver admission</Text><Text style={ui.body}>{event.registration ? 'Already in your tickets' : event.availability?.driver?.sold_out ? 'Sold out' : `${money(event.prices.driver)} · One per driver`}</Text></View><Text style={styles.ticketAction}>{event.registration ? 'Owned' : event.availability?.driver?.sold_out ? 'Full' : 'Buy ›'}</Text>
          </Pressable>
          <Pressable disabled={!!event.availability?.spectator?.sold_out} onPress={() => router.push({ pathname: '/event/[id]/spectator-checkout', params: { id: String(event.id) } })} style={({ pressed }) => [styles.ticketRow, styles.ticketDivider, pressed && styles.pressed, event.availability?.spectator?.sold_out && styles.ticketDisabled]}>
            <View style={styles.ticketIcon}><SymbolView name={{ ios: 'person.2.fill', android: 'person.2.fill', web: 'person.2.fill' } as any} tintColor={palette.orange} size={22} /></View><View style={styles.ticketCopy}><Text style={styles.ticketTitle}>Spectator admission</Text><Text style={ui.body}>{event.availability?.spectator?.sold_out ? 'Sold out' : `${money(event.prices.spectator)} · Buy for your guests`}</Text></View><Text style={styles.ticketAction}>{event.availability?.spectator?.sold_out ? 'Full' : 'Buy ›'}</Text>
          </Pressable>
        </Card>
      </> : null}
      <SectionTitle title="Vendors onsite" />
      {event.vendors?.length ? <View style={styles.vendorGrid}>{event.vendors.map((vendor, index) => <Card key={`${vendor.id}-${index}`} style={styles.vendor}><View style={styles.vendorLogo}><Text style={styles.vendorInitial}>{vendor.business_name.slice(0, 2).toUpperCase()}</Text></View><Text numberOfLines={2} style={styles.vendorName}>{vendor.business_name}</Text></Card>)}</View> : <Empty title="No vendors announced" detail="Paid event vendors will appear here." />}
    </> : null}
  </Screen>;
}

const styles = StyleSheet.create({
  line: { flexDirection: 'row', justifyContent: 'space-between', paddingTop: 12, marginTop: 12, borderTopWidth: 1, borderTopColor: palette.line },
  value: { color: palette.ink, fontWeight: '900' },
  booked: { backgroundColor: palette.greenSoft, borderRadius: 13, padding: 13, marginTop: 16 },
  bookedTitle: { color: palette.green, fontWeight: '900' },
  bookedText: { color: palette.green, marginTop: 3 },
  toolList: { paddingVertical: 2 },
  toolRow: { minHeight: 72, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 },
  toolDivider: { borderTopWidth: 1, borderTopColor: palette.line },
  toolIcon: { width: 42, height: 42, borderRadius: 13, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' },
  toolCopy: { flex: 1, gap: 2 },
  toolTitle: { color: palette.ink, fontSize: 16, fontWeight: '900' },
  arrow: { color: palette.orange, fontSize: 28 },
  pressed: { opacity: 0.6 },
  vendorGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 10 },
  vendor: { width: '48%', alignItems: 'center' },
  vendorLogo: { width: 76, height: 76, borderRadius: 20, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center', marginBottom: 10 },
  vendorInitial: { color: 'white', fontWeight: '900', fontSize: 21 },
  vendorName: { color: palette.ink, textAlign: 'center', fontWeight: '800' },
  ticketMenu: { paddingVertical: 3 }, ticketRow: { minHeight: 76, flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 12 }, ticketDivider: { borderTopWidth: 1, borderTopColor: palette.line }, ticketDisabled: { opacity: .55 }, ticketIcon: { width: 44, height: 44, borderRadius: 14, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, ticketCopy: { flex: 1 }, ticketTitle: { color: palette.ink, fontSize: 15, fontWeight: '900', marginBottom: 2 }, ticketAction: { color: palette.orange, fontSize: 12, fontWeight: '900' },
});
