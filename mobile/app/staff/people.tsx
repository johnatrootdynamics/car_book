import { router } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { Card, Empty, Field, Hero, Loading, Screen, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import { useAuth } from '@/providers/AuthProvider';

type Driver = {
  id: number;
  name: string;
  username?: string | null;
  email: string;
  driver_class: string;
  registered_count: number;
  attended_count: number;
  note_count: number;
  last_event_date?: string | null;
};

type Vendor = {
  id: number;
  business_name: string;
  website?: string | null;
  description?: string | null;
  contact_name?: string;
  email?: string;
  phone?: string;
};

export default function StaffPeopleScreen() {
  const { api } = useAuth();
  const [view, setView] = useState<'drivers' | 'vendors'>('drivers');
  const [query, setQuery] = useState('');
  const [drivers, setDrivers] = useState<Driver[]>([]);
  const [vendors, setVendors] = useState<Vendor[]>([]);
  const [loading, setLoading] = useState(true);
  const [ready, setReady] = useState(false);
  const [error, setError] = useState('');
  const requestSequence = useRef(0);

  const load = useCallback(async (nextView: 'drivers' | 'vendors', term: string, requestId: number) => {
    try {
      const body = await api<{ drivers?: Driver[]; vendors?: Vendor[] }>(`/staff/people?view=${nextView}&q=${encodeURIComponent(term.trim())}`);
      if (requestId !== requestSequence.current) return;
      if (nextView === 'drivers') setDrivers(body.drivers || []);
      else setVendors(body.vendors || []);
    } catch (caught) {
      if (requestId === requestSequence.current) setError(caught instanceof Error ? caught.message : 'Unable to load people.');
    } finally {
      if (requestId === requestSequence.current) {
        setLoading(false);
        setReady(true);
      }
    }
  }, [api]);

  useEffect(() => {
    const requestId = ++requestSequence.current;
    setLoading(true);
    setError('');
    const timer = setTimeout(() => load(view, query, requestId), query.trim() ? 300 : 0);
    return () => clearTimeout(timer);
  }, [load, query, view]);

  const switchView = (next: 'drivers' | 'vendors') => {
    if (next === view) return;
    requestSequence.current += 1;
    setReady(false);
    setQuery('');
    setView(next);
  };

  return <Screen>
    <Hero eyebrow="Track directory" title="People" subtitle="Drivers and vendors connected to your track." />
    <View style={styles.segment}>
      {(['drivers', 'vendors'] as const).map(option => <Pressable key={option} onPress={() => switchView(option)} style={[styles.segmentButton, view === option && styles.segmentActive]}><Text style={[styles.segmentText, view === option && styles.segmentTextActive]}>{option === 'drivers' ? 'Drivers' : 'Vendors'}</Text></Pressable>)}
    </View>
    <View style={styles.search}>
      <Field style={styles.searchField} value={query} onChangeText={setQuery} placeholder={`Search ${view} as you type`} autoCapitalize="none" autoCorrect={false} returnKeyType="search" />
      {loading && ready ? <Text style={styles.searching}>Searching…</Text> : null}
    </View>
    {error ? <Text style={styles.error}>{error}</Text> : null}
    {loading && !ready ? <Loading /> : view === 'drivers' ? <>
      {drivers.length ? drivers.map(driver => <Pressable key={driver.id} onPress={() => router.push({ pathname: '/staff/driver/[id]', params: { id: String(driver.id) } })}><Card style={styles.row}><View style={styles.avatar}><Text style={styles.initials}>{initials(driver.name)}</Text></View><View style={styles.copy}><View style={ui.between}><Text style={styles.name}>{driver.name}</Text><Text style={styles.classPill}>Class {driver.driver_class}</Text></View><Text style={ui.body}>{driver.email}</Text><Text style={styles.meta}>{driver.attended_count} attended · {driver.registered_count} registered · {driver.note_count} notes</Text></View><Text style={styles.arrow}>›</Text></Card></Pressable>) : <Empty title="No drivers found" detail={query.trim() ? "Try a different name, username, or email." : "Drivers appear after registering for an event at this track."} />}
    </> : <>
      {vendors.length ? vendors.map(vendor => <Card key={vendor.id} style={styles.row}><View style={styles.vendorAvatar}><Text style={styles.initials}>{initials(vendor.business_name)}</Text></View><View style={styles.copy}><Text style={styles.name}>{vendor.business_name}</Text>{vendor.contact_name ? <Text style={ui.body}>{vendor.contact_name}{vendor.email ? ` · ${vendor.email}` : ''}</Text> : null}<Text numberOfLines={2} style={styles.meta}>{vendor.description || vendor.website || 'Vendor profile'}</Text></View></Card>) : <Empty title="No vendors found" detail={query.trim() ? "Try a different business name or contact." : "Vendor accounts will appear here when they join TrackOps."} />}
    </>}
  </Screen>;
}

function initials(value: string) {
  return value.split(/\s+/).filter(Boolean).slice(0, 2).map(part => part[0]).join('').toUpperCase();
}

const styles = StyleSheet.create({
  segment: { flexDirection: 'row', backgroundColor: '#EAECF0', borderRadius: 14, padding: 4 },
  segmentButton: { flex: 1, minHeight: 42, alignItems: 'center', justifyContent: 'center', borderRadius: 11 },
  segmentActive: { backgroundColor: 'white' },
  segmentText: { color: palette.muted, fontWeight: '800' },
  segmentTextActive: { color: palette.ink },
  search: { position: 'relative' },
  searchField: { paddingRight: 100 },
  searching: { position: 'absolute', right: 14, top: 18, color: palette.muted, fontSize: 12, fontWeight: '700' },
  row: { flexDirection: 'row', alignItems: 'center', gap: 12, paddingVertical: 14 },
  avatar: { width: 48, height: 48, borderRadius: 15, backgroundColor: palette.navy, alignItems: 'center', justifyContent: 'center' },
  vendorAvatar: { width: 48, height: 48, borderRadius: 15, backgroundColor: palette.orange, alignItems: 'center', justifyContent: 'center' },
  initials: { color: 'white', fontWeight: '900', fontSize: 15 },
  copy: { flex: 1, gap: 3 },
  name: { color: palette.ink, fontSize: 16, fontWeight: '900', flexShrink: 1 },
  classPill: { color: '#C2410C', fontSize: 11, fontWeight: '900', backgroundColor: palette.orangeSoft, borderRadius: 999, paddingHorizontal: 8, paddingVertical: 4 },
  meta: { color: palette.muted, fontSize: 12, lineHeight: 17 },
  arrow: { color: palette.orange, fontSize: 28 },
  error: { color: palette.red, fontWeight: '800' },
});
