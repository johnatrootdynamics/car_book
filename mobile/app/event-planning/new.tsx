import * as ImagePicker from 'expo-image-picker';
import { router } from 'expo-router';
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { Alert, Image, PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';
import Svg, { Path } from 'react-native-svg';

import { ChoiceChip, NativeDateTimeField } from '@/components/planning';
import { Button, Card, Empty, Field, Hero, Loading, Screen, SectionTitle, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Planning = {
  defaults: {
    event_type: 'public'; date: string; driver_price: number; spectator_price: number; vendor_price: number;
    driver_capacity: number; spectator_capacity: number; vendor_capacity: number; default_waiver_id: number | null;
  };
  waivers: { id: number; title: string; is_active: boolean; required_for_checkin: boolean }[];
  layouts: { id: number; name: string; image_url?: string | null }[];
};
type ImageChoice = { uri: string; dataUrl: string };
type LayoutMode = 'default' | 'existing' | 'upload' | 'draw';
type DrawingPadHandle = { exportImage: () => Promise<string | null> };

export default function CreateEventScreen() {
  const { account, api } = useAuth();
  const drawingRef = useRef<DrawingPadHandle>(null);
  const [planning, setPlanning] = useState<Planning | null>(null);
  const [loadingError, setLoadingError] = useState('');
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState('');
  const [eventType, setEventType] = useState<'public' | 'private'>('public');
  const [name, setName] = useState('');
  const [eventDate, setEventDate] = useState<Date | null>(null);
  const [startTime, setStartTime] = useState<Date | null>(null);
  const [endTime, setEndTime] = useState<Date | null>(null);
  const [driverPrice, setDriverPrice] = useState('0.00');
  const [spectatorPrice, setSpectatorPrice] = useState('25.00');
  const [vendorPrice, setVendorPrice] = useState('100.00');
  const [driverCapacity, setDriverCapacity] = useState('50');
  const [spectatorCapacity, setSpectatorCapacity] = useState('100');
  const [vendorCapacity, setVendorCapacity] = useState('4');
  const [waiverId, setWaiverId] = useState<number | null>(null);
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('default');
  const [layoutId, setLayoutId] = useState<number | null>(null);
  const [layoutName, setLayoutName] = useState('');
  const [layoutImage, setLayoutImage] = useState<ImageChoice | null>(null);
  const [thumbnail, setThumbnail] = useState<ImageChoice | null>(null);

  useEffect(() => {
    if (account?.type !== 'employee' || account.role !== 'office_staff') return;
    api<Planning>('/staff/event-planning').then(body => {
      setPlanning(body);
      setEventDate(dateFromValue(body.defaults.date));
      setDriverPrice(body.defaults.driver_price.toFixed(2));
      setSpectatorPrice(body.defaults.spectator_price.toFixed(2));
      setVendorPrice(body.defaults.vendor_price.toFixed(2));
      setDriverCapacity(String(body.defaults.driver_capacity));
      setSpectatorCapacity(String(body.defaults.spectator_capacity));
      setVendorCapacity(String(body.defaults.vendor_capacity));
      setWaiverId(body.defaults.default_waiver_id);
    }).catch(caught => setLoadingError(caught instanceof Error ? caught.message : 'Unable to load event planning.'));
  }, [account, api]);

  if (account?.type !== 'employee' || account.role !== 'office_staff') return <Screen><Empty title="Office staff only" detail="Event creation is available to back-office track staff." /></Screen>;
  if (!planning && !loadingError) return <Loading />;
  if (!planning) return <Screen><Empty title="Event planning unavailable" detail={loadingError} /></Screen>;

  const chooseType = (value: 'public' | 'private') => {
    setEventType(value);
    setError('');
    if (value === 'private') {
      if (!startTime) setStartTime(timeFromValue('09:00'));
      if (!endTime) setEndTime(timeFromValue('17:00'));
      if (driverPrice === '0.00') setDriverPrice('2500.00');
      if (driverCapacity === '50') setDriverCapacity('20');
      if (!name) setName('Private track rental');
    }
  };

  const pickImage = async (target: 'layout' | 'thumbnail') => {
    const result = await ImagePicker.launchImageLibraryAsync({
      mediaTypes: ['images'], allowsEditing: true, quality: .8, base64: true,
      aspect: target === 'layout' ? [16, 9] : [16, 9],
    });
    if (result.canceled) return;
    const asset = result.assets[0];
    if (!asset.base64) {
      setError('That image could not be prepared for upload.');
      return;
    }
    const mime = ['image/jpeg', 'image/png', 'image/webp'].includes(asset.mimeType || '') ? asset.mimeType : 'image/jpeg';
    const choice = { uri: asset.uri, dataUrl: `data:${mime};base64,${asset.base64}` };
    if (target === 'layout') setLayoutImage(choice); else setThumbnail(choice);
  };

  const submit = async () => {
    setSaving(true); setError('');
    try {
      let drawingImage: string | null = null;
      if (layoutMode === 'draw') drawingImage = await drawingRef.current?.exportImage() || null;
      const body = {
        event_type: eventType,
        name,
        date: eventDate ? dateValue(eventDate) : '',
        start_time: startTime ? timeValue(startTime) : '',
        end_time: endTime ? timeValue(endTime) : '',
        driver_price: driverPrice,
        spectator_price: spectatorPrice,
        vendor_price: vendorPrice,
        driver_capacity: driverCapacity,
        spectator_capacity: spectatorCapacity,
        vendor_capacity: vendorCapacity,
        waiver_id: waiverId,
        layout_mode: layoutMode,
        layout_id: layoutId,
        layout_name: layoutName,
        layout_image: layoutMode === 'draw' ? drawingImage : layoutImage?.dataUrl,
        thumbnail_image: thumbnail?.dataUrl,
      };
      const result = await api<{ created: 'event' | 'rental_slot'; event?: { id: number }; slot?: { id: number } }>('/staff/events', { method: 'POST', body: JSON.stringify(body) });
      if (result.created === 'event' && result.event) {
        Alert.alert('Event created', `${name} is ready for registrations.`);
        router.replace(`/event/${result.event.id}`);
      } else {
        Alert.alert('Rental availability created', `${name} is now visible on the rental calendar.`);
        router.replace('/event-planning/rentals');
      }
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to create the event.');
    } finally { setSaving(false); }
  };

  const activeWaivers = planning.waivers.filter(item => item.is_active);
  return <Screen>
    <Hero eyebrow="Event planning" title="Create an event" subtitle="Build the date, inventory, pricing, waiver, and track layout in one native workflow." />
    <SectionTitle title="Event type" />
    <Card style={styles.sectionCard}>
      <View style={styles.chips}><ChoiceChip label="Public event" selected={eventType === 'public'} onPress={() => chooseType('public')} /><ChoiceChip label="Private rental" selected={eventType === 'private'} onPress={() => chooseType('private')} /></View>
      <Text style={styles.help}>{eventType === 'public' ? 'Sell driver, spectator, and vendor admission.' : 'Publish a private track window for one driver to reserve.'}</Text>
    </Card>

    <SectionTitle title="Basics" />
    <Card style={styles.sectionCard}>
      <LabeledField label={eventType === 'public' ? 'Event name' : 'Rental name'} value={name} onChangeText={setName} placeholder={eventType === 'public' ? 'Summer open track day' : 'Private track rental'} maxLength={200} />
      <NativeDateTimeField label={eventType === 'public' ? 'Event date' : 'Available date'} mode="date" value={eventDate} minimumDate={startOfToday()} onChange={setEventDate} />
      <View style={styles.twoColumn}><View style={styles.column}><NativeDateTimeField label="Start time" mode="time" value={startTime} optional={eventType === 'public'} onChange={setStartTime} /></View><View style={styles.column}><NativeDateTimeField label="End time" mode="time" value={endTime} optional={eventType === 'public'} onChange={setEndTime} /></View></View>
    </Card>

    {eventType === 'public' ? <>
      <SectionTitle title="Driver waiver" />
      <Card style={styles.sectionCard}>
        {activeWaivers.length ? <View style={styles.chips}>{activeWaivers.map(waiver => <ChoiceChip key={waiver.id} label={waiver.title} selected={waiverId === waiver.id} onPress={() => setWaiverId(waiver.id)} />)}</View> : <Text style={styles.warning}>No active waiver is configured. Add one in Track Settings before creating a public event.</Text>}
        <Text style={styles.help}>This is the waiver every registered driver must complete before check-in.</Text>
      </Card>
    </> : null}

    <SectionTitle title={eventType === 'public' ? 'Admission pricing' : 'Rental terms'} />
    <Card style={styles.sectionCard}>
      <LabeledField label={eventType === 'public' ? 'Driver price (USD)' : 'Rental price (USD)'} value={driverPrice} onChangeText={setDriverPrice} keyboardType="decimal-pad" />
      {eventType === 'public' ? <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Spectator (USD)" value={spectatorPrice} onChangeText={setSpectatorPrice} keyboardType="decimal-pad" /></View><View style={styles.column}><LabeledField label="Vendor/person" value={vendorPrice} onChangeText={setVendorPrice} keyboardType="decimal-pad" /></View></View> : null}
    </Card>

    <SectionTitle title={eventType === 'public' ? 'Admission limits' : 'Driver limit'} />
    <Card style={styles.sectionCard}>
      {eventType === 'public' ? <Text style={styles.help}>Use 0 for unlimited capacity.</Text> : null}
      <LabeledField label="Drivers" value={driverCapacity} onChangeText={setDriverCapacity} keyboardType="number-pad" />
      {eventType === 'public' ? <View style={styles.twoColumn}><View style={styles.column}><LabeledField label="Spectators" value={spectatorCapacity} onChangeText={setSpectatorCapacity} keyboardType="number-pad" /></View><View style={styles.column}><LabeledField label="Vendor reps" value={vendorCapacity} onChangeText={setVendorCapacity} keyboardType="number-pad" /></View></View> : null}
    </Card>

    {eventType === 'public' ? <>
      <SectionTitle title="Track layout" />
      <Card style={styles.sectionCard}>
        <View style={styles.chips}><ChoiceChip label="Track default" selected={layoutMode === 'default'} onPress={() => setLayoutMode('default')} /><ChoiceChip label="Existing" selected={layoutMode === 'existing'} onPress={() => setLayoutMode('existing')} /><ChoiceChip label="Upload" selected={layoutMode === 'upload'} onPress={() => setLayoutMode('upload')} /><ChoiceChip label="Draw" selected={layoutMode === 'draw'} onPress={() => setLayoutMode('draw')} /></View>
        {layoutMode === 'existing' ? planning.layouts.length ? <View style={styles.layoutList}>{planning.layouts.map(layout => <Pressable key={layout.id} onPress={() => setLayoutId(layout.id)} style={[styles.layoutOption, layoutId === layout.id && styles.layoutOptionSelected]}>{layout.image_url ? <Image source={{ uri: layout.image_url }} style={styles.layoutThumb} /> : <View style={styles.layoutPlaceholder}><Text style={styles.layoutPlaceholderText}>MAP</Text></View>}<Text style={styles.layoutOptionText}>{layout.name}</Text></Pressable>)}</View> : <Text style={styles.warning}>No saved layouts yet. Use the track default, upload one, or draw one now.</Text> : null}
        {layoutMode === 'upload' ? <><LabeledField label="Layout name" value={layoutName} onChangeText={setLayoutName} placeholder={name || 'South loop'} maxLength={120} /><Button tone="secondary" title={layoutImage ? 'Choose a different image' : 'Choose layout image'} onPress={() => pickImage('layout')} />{layoutImage ? <Image source={{ uri: layoutImage.uri }} style={styles.preview} /> : null}</> : null}
        {layoutMode === 'draw' ? <><LabeledField label="Layout name" value={layoutName} onChangeText={setLayoutName} placeholder={name || 'Custom layout'} maxLength={120} /><DrawingPad ref={drawingRef} /></> : null}
      </Card>

      <SectionTitle title="Event thumbnail" />
      <Card style={styles.sectionCard}>
        <Button tone="secondary" title={thumbnail ? 'Choose a different thumbnail' : 'Choose thumbnail'} onPress={() => pickImage('thumbnail')} />
        {thumbnail ? <><Image source={{ uri: thumbnail.uri }} style={styles.preview} /><Pressable onPress={() => setThumbnail(null)}><Text style={styles.removeText}>Remove thumbnail</Text></Pressable></> : <Text style={styles.help}>Optional. This image appears with the event throughout Track Ops.</Text>}
      </Card>
    </> : null}

    {error ? <View style={styles.errorBox}><Text style={styles.errorText}>{error}</Text></View> : null}
    <Button title={saving ? eventType === 'public' ? 'Creating event…' : 'Publishing rental…' : eventType === 'public' ? 'Create event' : 'Publish rental availability'} onPress={submit} disabled={saving || (eventType === 'public' && !activeWaivers.length)} />
  </Screen>;
}

const DrawingPad = forwardRef<DrawingPadHandle>(function DrawingPad(_, ref) {
  const svgRef = useRef<Svg>(null);
  const [paths, setPaths] = useState<string[]>([]);
  const pan = useMemo(() => PanResponder.create({
    onStartShouldSetPanResponder: () => true,
    onMoveShouldSetPanResponder: () => true,
    onPanResponderGrant: event => {
      const { locationX, locationY } = event.nativeEvent;
      setPaths(current => [...current, `M ${locationX.toFixed(1)} ${locationY.toFixed(1)}`]);
    },
    onPanResponderMove: event => {
      const { locationX, locationY } = event.nativeEvent;
      setPaths(current => current.map((path, index) => index === current.length - 1 ? `${path} L ${locationX.toFixed(1)} ${locationY.toFixed(1)}` : path));
    },
  }), []);
  useImperativeHandle(ref, () => ({ exportImage: () => new Promise(resolve => {
    if (!paths.length || !svgRef.current) { resolve(null); return; }
    svgRef.current.toDataURL(data => resolve(`data:image/png;base64,${data}`), { width: 920, height: 480 });
  }) }), [paths]);
  return <View style={styles.drawingBlock}>
    <View style={styles.drawingPad} {...pan.panHandlers}><Svg ref={svgRef} width="100%" height="100%" viewBox="0 0 340 180"><Path d="M 0 0 H 340 V 180 H 0 Z" fill="#0F172A" />{paths.map((path, index) => <Path key={index} d={path} fill="none" stroke="#F8FAFC" strokeWidth={4} strokeLinecap="round" strokeLinejoin="round" />)}</Svg></View>
    <View style={styles.drawingFooter}><Text style={styles.help}>Draw the route with your finger.</Text><Pressable onPress={() => setPaths([])}><Text style={styles.removeText}>Clear</Text></Pressable></View>
  </View>;
});

function LabeledField({ label, ...props }: { label: string } & React.ComponentProps<typeof Field>) { return <View style={styles.fieldGroup}><Text style={ui.label}>{label}</Text><Field {...props} /></View>; }
function startOfToday() { const value = new Date(); value.setHours(0, 0, 0, 0); return value; }
function dateFromValue(value: string) { const [year, month, day] = value.split('-').map(Number); return new Date(year, month - 1, day, 12); }
function dateValue(value: Date) { return `${value.getFullYear()}-${String(value.getMonth() + 1).padStart(2, '0')}-${String(value.getDate()).padStart(2, '0')}`; }
function timeFromValue(value: string) { const [hours, minutes] = value.split(':').map(Number); const result = new Date(); result.setHours(hours, minutes, 0, 0); return result; }
function timeValue(value: Date) { return `${String(value.getHours()).padStart(2, '0')}:${String(value.getMinutes()).padStart(2, '0')}`; }

const styles = StyleSheet.create({
  sectionCard: { gap: 15 }, chips: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 }, help: { color: palette.muted, fontSize: 12, lineHeight: 18 }, warning: { color: '#B54708', fontSize: 13, fontWeight: '800', lineHeight: 19, backgroundColor: '#FFFAEB', borderRadius: 12, padding: 12 },
  fieldGroup: { gap: 0 }, twoColumn: { flexDirection: 'row', alignItems: 'flex-start', gap: 10 }, column: { flex: 1 },
  layoutList: { gap: 9 }, layoutOption: { minHeight: 64, borderRadius: 14, borderWidth: 1, borderColor: palette.line, flexDirection: 'row', alignItems: 'center', gap: 12, overflow: 'hidden', paddingRight: 12 }, layoutOptionSelected: { borderColor: palette.orange, backgroundColor: palette.orangeSoft }, layoutThumb: { width: 82, height: 62, resizeMode: 'cover' }, layoutPlaceholder: { width: 82, height: 62, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' }, layoutPlaceholderText: { color: '#FDBA74', fontSize: 10, fontWeight: '900', letterSpacing: 1 }, layoutOptionText: { color: palette.ink, fontWeight: '900', flex: 1 },
  preview: { width: '100%', height: 180, borderRadius: 14, resizeMode: 'cover', backgroundColor: palette.line }, removeText: { color: palette.red, fontSize: 12, fontWeight: '900' },
  drawingBlock: { gap: 8 }, drawingPad: { height: 180, borderRadius: 16, overflow: 'hidden', borderWidth: 2, borderColor: '#344054', backgroundColor: '#0F172A' }, drawingFooter: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' },
  errorBox: { borderRadius: 14, padding: 14, backgroundColor: palette.redSoft }, errorText: { color: palette.red, fontWeight: '800', lineHeight: 19 },
});
