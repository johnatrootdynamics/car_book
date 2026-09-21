import { useFocusEffect } from 'expo-router';
import { useCallback, useMemo, useState } from 'react';
import { Alert, Pressable, StyleSheet, Text, View } from 'react-native';

import { NativeDateTimeField } from '@/components/planning';
import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { eventDate, money } from '@/lib/format';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type RentalSlot = {
  id: number; name: string; date: string; start_time: string; end_time: string;
  price: number; driver_limit: number; status: 'open' | 'held' | 'booked';
  booking?: { id: number; name: string; event_id?: number | null } | null;
};
type CalendarEvent = { id: number; name: string; date: string; start_time?: string | null; end_time?: string | null };
type Rentals = {
  month: { value: string; label: string; previous: string; next: string };
  today: string; slots: RentalSlot[]; upcoming: RentalSlot[]; events: CalendarEvent[];
};

export default function RentalAvailabilityScreen() {
  const { account, api } = useAuth();
  const [month, setMonth] = useState(currentMonth());
  const [data, setData] = useState<Rentals | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const [busy, setBusy] = useState(false);
  const [selectedDate, setSelectedDate] = useState(dateFromValue(todayValue()));
  const [name, setName] = useState('Private track rental');
  const [startTime, setStartTime] = useState(timeFromValue('09:00'));
  const [endTime, setEndTime] = useState(timeFromValue('17:00'));
  const [price, setPrice] = useState('2500.00');
  const [driverLimit, setDriverLimit] = useState('20');

  const load = useCallback(async () => {
    if (account?.type !== 'employee' || account.role !== 'office_staff') return;
    setLoading(true); setError('');
    try { setData(await api<Rentals>(`/staff/private-rentals?month=${month}`)); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to load rental availability.'); }
    finally { setLoading(false); }
  }, [account, api, month]);
  useFocusEffect(useCallback(() => { load(); }, [load]));

  const days = useMemo(() => calendarDays(month), [month]);
  const monthSlots = useMemo(() => groupByDate(data?.slots || []), [data?.slots]);
  const monthEvents = useMemo(() => groupByDate(data?.events || []), [data?.events]);
  const selectedValue = dateValue(selectedDate);
  const selectedSlots = monthSlots[selectedValue] || [];
  const selectedEvents = monthEvents[selectedValue] || [];

  if (account?.type !== 'employee' || account.role !== 'office_staff') return <Screen><Empty title="Office staff only" detail="Rental availability is managed by back-office track staff." /></Screen>;
  if (loading && !data) return <Loading />;
  if (!data) return <Screen><Empty title="Rental calendar unavailable" detail={error || 'Try again in a moment.'} /><Button title="Try again" onPress={load} /></Screen>;

  const selectDay = (value: string) => {
    const next = dateFromValue(value);
    if (value < data.today) return;
    setSelectedDate(next); setNotice(''); setError('');
  };
  const create = async () => {
    setBusy(true); setError(''); setNotice('');
    try {
      const body = await api<Rentals>('/staff/private-rentals', { method: 'POST', body: JSON.stringify({ name, date: selectedValue, start_time: timeValue(startTime), end_time: timeValue(endTime), price, driver_limit: driverLimit }) });
      setData(body); setMonth(body.month.value); setNotice('Rental availability published.');
    } catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to add rental availability.'); }
    finally { setBusy(false); }
  };
  const remove = (slot: RentalSlot) => Alert.alert('Remove rental availability?', `${slot.name} · ${eventDate(slot.date)} at ${clockLabel(slot.start_time)}`, [{ text: 'Keep slot', style: 'cancel' }, { text: 'Remove', style: 'destructive', onPress: async () => {
    setBusy(true); setError(''); setNotice('');
    try { setData(await api<Rentals>(`/staff/private-rentals/${slot.id}`, { method: 'DELETE' })); setNotice('Rental availability removed.'); }
    catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to remove rental availability.'); }
    finally { setBusy(false); }
  } }]);

  return <Screen>
    <Hero eyebrow="Office staff" title="Rental availability" subtitle="Publish private track windows, see holds and bookings, and prevent scheduling conflicts." />
    {notice ? <Notice tone="success" text={notice} /> : null}{error ? <Notice tone="error" text={error} /> : null}

    <Card style={styles.calendarCard}>
      <View style={styles.calendarHead}><View><Text style={styles.kicker}>TRACK AVAILABILITY</Text><Text style={styles.monthTitle}>{data.month.label}</Text></View><View style={styles.monthNav}><Pressable onPress={() => setMonth(data.month.previous)} style={styles.navButton}><Text style={styles.navText}>‹</Text></Pressable><Pressable onPress={() => setMonth(currentMonth())} style={styles.todayButton}><Text style={styles.todayText}>Today</Text></Pressable><Pressable onPress={() => setMonth(data.month.next)} style={styles.navButton}><Text style={styles.navText}>›</Text></Pressable></View></View>
      <View style={styles.legend}><Legend color="#12B76A" label="Open" /><Legend color="#F79009" label="Held" /><Legend color="#7F56D9" label="Booked" /><Legend color={palette.navy} label="Event" /></View>
      <View style={styles.weekRow}>{['S', 'M', 'T', 'W', 'T', 'F', 'S'].map((day, index) => <Text key={`${day}-${index}`} style={styles.weekday}>{day}</Text>)}</View>
      <View style={styles.calendarGrid}>{days.map(day => {
        const slots = monthSlots[day.value] || [];
        const events = monthEvents[day.value] || [];
        const past = day.value < data.today;
        const selected = day.value === selectedValue;
        return <Pressable key={day.value} disabled={past} onPress={() => selectDay(day.value)} style={[styles.dayCell, !day.inMonth && styles.outsideDay, past && styles.pastDay, selected && styles.selectedDay]}>
          <Text style={[styles.dayNumber, selected && styles.selectedDayText]}>{day.day}</Text>
          <View style={styles.daySignals}>{slots.slice(0, 3).map(slot => <View key={slot.id} style={[styles.signal, { backgroundColor: statusColor(slot.status) }]} />)}{events.length ? <View style={[styles.signal, { backgroundColor: palette.navy }]} /> : null}</View>
        </Pressable>;
      })}</View>
    </Card>

    <Card style={styles.selectedCard}>
      <View style={ui.between}><View><Text style={styles.kicker}>SELECTED DATE</Text><Text style={styles.selectedTitle}>{eventDate(selectedValue)}</Text></View><Text style={styles.selectedCount}>{selectedSlots.length + selectedEvents.length}</Text></View>
      {selectedEvents.map(event => <View key={`event-${event.id}`} style={styles.dateItem}><View style={[styles.dateMark, { backgroundColor: palette.navy }]} /><View style={{ flex: 1 }}><Text style={styles.itemTitle}>{event.name}</Text><Text style={ui.body}>{timeRange(event.start_time, event.end_time)} · Existing event</Text></View></View>)}
      {selectedSlots.map(slot => <View key={`slot-${slot.id}`} style={styles.dateItem}><View style={[styles.dateMark, { backgroundColor: statusColor(slot.status) }]} /><View style={{ flex: 1 }}><Text style={styles.itemTitle}>{slot.name}</Text><Text style={ui.body}>{clockLabel(slot.start_time)}–{clockLabel(slot.end_time)} · {money(slot.price)}</Text></View><Status value={slot.status} /></View>)}
      {!selectedEvents.length && !selectedSlots.length ? <Text style={styles.help}>No scheduled events or rental windows on this date.</Text> : null}
    </Card>

    <SectionTitle title="Add availability" />
    <Card style={styles.formCard}>
      <Text style={styles.help}>Times are checked against events and other private-rental windows.</Text>
      <LabeledField label="Slot name" value={name} onChangeText={setName} maxLength={120} />
      <NativeDateTimeField label="Available date" value={selectedDate} mode="date" minimumDate={dateFromValue(data.today)} onChange={value => value && setSelectedDate(value)} />
      <View style={styles.twoColumn}><View style={styles.column}><NativeDateTimeField label="Start time" value={startTime} mode="time" onChange={value => value && setStartTime(value)} /></View><View style={styles.column}><NativeDateTimeField label="End time" value={endTime} mode="time" onChange={value => value && setEndTime(value)} /></View></View>
      <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Price (USD)" value={price} onChangeText={setPrice} keyboardType="decimal-pad" /></View><View style={styles.column}><LabeledField label="Driver limit" value={driverLimit} onChangeText={setDriverLimit} keyboardType="number-pad" /></View></View>
      <View style={styles.guardrail}><Text style={styles.guardrailIcon}>✓</Text><Text style={styles.guardrailText}>A slot cannot overlap an event or another private rental.</Text></View>
      <Button title={busy ? 'Publishing…' : 'Publish rental availability'} onPress={create} disabled={busy} />
    </Card>

    <SectionTitle title="Upcoming rental slots" />
    {data.upcoming.length ? data.upcoming.map(slot => <Card key={slot.id} style={styles.slotCard}>
      <View style={styles.slotDate}><Text style={styles.slotMonth}>{dateFromValue(slot.date).toLocaleString('en-US', { month: 'short' }).toUpperCase()}</Text><Text style={styles.slotDay}>{dateFromValue(slot.date).getDate()}</Text></View>
      <View style={styles.slotCopy}><View style={styles.slotHeading}><Text style={styles.slotName}>{slot.name}</Text><Status value={slot.status} /></View><Text style={ui.body}>{clockLabel(slot.start_time)}–{clockLabel(slot.end_time)} · {money(slot.price)} · {slot.driver_limit} drivers</Text><Text style={styles.bookingText}>{slot.booking ? `${slot.booking.name} · ${slot.status === 'booked' ? 'Confirmed renter' : 'Payment hold'}` : 'Visible to drivers'}</Text></View>
      {slot.status === 'open' ? <Pressable disabled={busy} onPress={() => remove(slot)} style={styles.removeButton}><Text style={styles.removeText}>Remove</Text></Pressable> : null}
    </Card>) : <Empty title="No rental availability yet" detail="Choose a date and publish the first private-rental window." />}
  </Screen>;
}

function LabeledField({ label, ...props }: { label: string } & React.ComponentProps<typeof Field>) { return <View><Text style={ui.label}>{label}</Text><Field {...props} /></View>; }
function Legend({ color, label }: { color: string; label: string }) { return <View style={styles.legendItem}><View style={[styles.legendDot, { backgroundColor: color }]} /><Text style={styles.legendText}>{label}</Text></View>; }
function Status({ value }: { value: RentalSlot['status'] }) { return <View style={[styles.status, { backgroundColor: statusSoft(value) }]}><Text style={[styles.statusText, { color: statusColor(value) }]}>{value === 'open' ? 'Open' : value === 'held' ? 'Held' : 'Booked'}</Text></View>; }
function Notice({ tone, text }: { tone: 'success' | 'error'; text: string }) { return <View style={[styles.notice, tone === 'success' ? styles.successNotice : styles.errorNotice]}><Text style={[styles.noticeText, { color: tone === 'success' ? palette.green : palette.red }]}>{text}</Text></View>; }
function statusColor(value: RentalSlot['status']) { return value === 'open' ? '#12B76A' : value === 'held' ? '#F79009' : '#7F56D9'; }
function statusSoft(value: RentalSlot['status']) { return value === 'open' ? '#ECFDF3' : value === 'held' ? '#FFFAEB' : '#F4F3FF'; }
function groupByDate<T extends { date: string }>(items: T[]) { return items.reduce<Record<string, T[]>>((result, item) => { (result[item.date] ||= []).push(item); return result; }, {}); }
function currentMonth() { const value = new Date(); return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}`; }
function todayValue() { return dateValue(new Date()); }
function dateFromValue(value: string) { const [year, month, day] = value.split('-').map(Number); return new Date(year, month - 1, day, 12); }
function dateValue(value: Date) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`; }
function timeFromValue(value: string) { const [hours, minutes] = value.split(':').map(Number); const result = new Date(); result.setHours(hours, minutes, 0, 0); return result; }
function timeValue(value: Date) { return `${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}`; }
function clockLabel(value?: string | null) { if (!value) return 'All day'; const [hourValue, minute = '00'] = value.slice(0, 5).split(':'); const hour = Number(hourValue); return `${hour % 12 || 12}:${minute} ${hour < 12 ? 'AM' : 'PM'}`; }
function timeRange(start?: string | null, end?: string | null) { return start && end ? `${clockLabel(start)}–${clockLabel(end)}` : 'All day'; }
function calendarDays(monthValue: string) { const [year, month] = monthValue.split('-').map(Number); const first = new Date(year, month - 1, 1, 12); const start = new Date(first); start.setDate(1 - first.getDay()); const count = Math.ceil((first.getDay() + new Date(year, month, 0).getDate()) / 7) * 7; return Array.from({ length: count }, (_, index) => { const value = new Date(start); value.setDate(start.getDate() + index); return { value: dateValue(value), day: value.getDate(), inMonth: value.getMonth() === month - 1 }; }); }

const styles = StyleSheet.create({
  notice: { borderRadius: 14, padding: 14 }, successNotice: { backgroundColor: palette.greenSoft }, errorNotice: { backgroundColor: palette.redSoft }, noticeText: { fontWeight: '800' },
  calendarCard: { gap: 13, padding: 14 }, calendarHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', gap: 10 }, kicker: { color: palette.orange, fontSize: 10, fontWeight: '900', letterSpacing: 1 }, monthTitle: { color: palette.ink, fontSize: 21, fontWeight: '900', marginTop: 3 }, monthNav: { flexDirection: 'row', alignItems: 'center', gap: 6 }, navButton: { width: 38, height: 38, borderRadius: 12, borderWidth: 1, borderColor: palette.line, alignItems: 'center', justifyContent: 'center' }, navText: { color: palette.ink, fontSize: 27, lineHeight: 28 }, todayButton: { height: 38, borderRadius: 12, backgroundColor: palette.orangeSoft, paddingHorizontal: 11, alignItems: 'center', justifyContent: 'center' }, todayText: { color: '#C2410C', fontSize: 12, fontWeight: '900' },
  legend: { flexDirection: 'row', flexWrap: 'wrap', gap: 12 }, legendItem: { flexDirection: 'row', alignItems: 'center', gap: 5 }, legendDot: { width: 8, height: 8, borderRadius: 4 }, legendText: { color: palette.muted, fontSize: 10, fontWeight: '800' }, weekRow: { flexDirection: 'row' }, weekday: { width: '14.285%', textAlign: 'center', color: palette.muted, fontSize: 10, fontWeight: '900' }, calendarGrid: { flexDirection: 'row', flexWrap: 'wrap' }, dayCell: { width: '14.285%', aspectRatio: .82, borderRadius: 10, alignItems: 'center', justifyContent: 'center', gap: 4 }, outsideDay: { opacity: .32 }, pastDay: { opacity: .25 }, selectedDay: { backgroundColor: palette.navy }, dayNumber: { color: palette.ink, fontSize: 13, fontWeight: '800' }, selectedDayText: { color: 'white' }, daySignals: { minHeight: 4, flexDirection: 'row', gap: 2 }, signal: { width: 4, height: 4, borderRadius: 2 },
  selectedCard: { gap: 11 }, selectedTitle: { color: palette.ink, fontSize: 17, fontWeight: '900', marginTop: 3 }, selectedCount: { minWidth: 31, height: 31, borderRadius: 10, backgroundColor: palette.orangeSoft, textAlign: 'center', textAlignVertical: 'center', color: '#C2410C', fontWeight: '900', paddingTop: 6 }, dateItem: { borderTopWidth: 1, borderTopColor: palette.line, paddingTop: 10, flexDirection: 'row', alignItems: 'center', gap: 10 }, dateMark: { width: 9, height: 34, borderRadius: 5 }, itemTitle: { color: palette.ink, fontWeight: '900' }, help: { color: palette.muted, fontSize: 12, lineHeight: 18 },
  formCard: { gap: 14 }, twoColumn: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 }, column: { flex: 1 }, guardrail: { flexDirection: 'row', alignItems: 'center', gap: 8, borderRadius: 12, padding: 11, backgroundColor: palette.greenSoft }, guardrailIcon: { color: palette.green, fontWeight: '900' }, guardrailText: { color: palette.green, fontSize: 12, fontWeight: '800', flex: 1 },
  slotCard: { flexDirection: 'row', alignItems: 'center', gap: 12 }, slotDate: { width: 52, height: 58, borderRadius: 14, backgroundColor: palette.orangeSoft, alignItems: 'center', justifyContent: 'center' }, slotMonth: { color: '#C2410C', fontSize: 9, fontWeight: '900' }, slotDay: { color: palette.orange, fontSize: 21, fontWeight: '900' }, slotCopy: { flex: 1, gap: 3 }, slotHeading: { flexDirection: 'row', alignItems: 'center', gap: 7 }, slotName: { color: palette.ink, fontSize: 15, fontWeight: '900', flex: 1 }, bookingText: { color: palette.muted, fontSize: 11, fontWeight: '700' }, status: { borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 }, statusText: { fontSize: 9, fontWeight: '900', textTransform: 'uppercase' }, removeButton: { alignSelf: 'stretch', justifyContent: 'center', paddingHorizontal: 3 }, removeText: { color: palette.red, fontSize: 11, fontWeight: '900' },
});
