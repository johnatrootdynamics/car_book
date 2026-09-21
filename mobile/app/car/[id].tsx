import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Alert, StyleSheet, Text, View } from 'react-native';

import { Button, Card, Field, Loading, Screen, ui } from '@/components/ui';
import { palette } from '@/lib/theme';
import type { Car } from '@/lib/types';
import { useAuth } from '@/providers/AuthProvider';

export default function CarFormScreen() {
  const params = useLocalSearchParams<{ id: string }>();
  const carId = params.id;
  const creating = carId === 'new';
  const { api } = useAuth();
  const [loading, setLoading] = useState(!creating);
  const [saving, setSaving] = useState(false);
  const [year, setYear] = useState('');
  const [make, setMake] = useState('');
  const [model, setModel] = useState('');
  const [color, setColor] = useState('');
  const [error, setError] = useState('');

  useEffect(() => {
    if (creating) return;
    api<{ cars: Car[] }>('/driver/garage').then(body => {
      const car = body.cars.find(item => item.id === Number(carId));
      if (!car) throw new Error('Vehicle not found.');
      setYear(String(car.year)); setMake(car.make); setModel(car.model); setColor(car.color || '');
    }).catch(caught => setError(caught instanceof Error ? caught.message : 'Unable to load vehicle.')).finally(() => setLoading(false));
  }, [api, carId, creating]);

  const save = async () => {
    setSaving(true); setError('');
    try {
      await api(creating ? '/driver/garage' : `/driver/garage/${carId}`, {
        method: creating ? 'POST' : 'PUT',
        body: JSON.stringify({ year, make, model, color }),
      });
      router.back();
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : 'Unable to save vehicle.');
    } finally {
      setSaving(false);
    }
  };

  const remove = () => Alert.alert('Remove this car?', 'A car connected to an event or rental cannot be removed.', [
    { text: 'Cancel', style: 'cancel' },
    { text: 'Remove', style: 'destructive', onPress: async () => {
      setSaving(true); setError('');
      try { await api(`/driver/garage/${carId}`, { method: 'DELETE' }); router.back(); }
      catch (caught) { setError(caught instanceof Error ? caught.message : 'Unable to remove vehicle.'); setSaving(false); }
    } },
  ]);

  if (loading) return <Loading />;
  return <Screen>
    <View style={styles.heading}><Text style={styles.eyebrow}>YOUR GARAGE</Text><Text style={styles.title}>{creating ? 'Add a car' : 'Edit car'}</Text><Text style={ui.body}>Keep the vehicle details used for registration and inspection accurate.</Text></View>
    <Card style={styles.form}>
      <View><Text style={ui.label}>Model year</Text><Field keyboardType="number-pad" maxLength={4} placeholder="2024" value={year} onChangeText={setYear} /></View>
      <View><Text style={ui.label}>Make</Text><Field autoCapitalize="words" placeholder="Porsche" value={make} onChangeText={setMake} /></View>
      <View><Text style={ui.label}>Model</Text><Field autoCapitalize="words" placeholder="911 GT3" value={model} onChangeText={setModel} /></View>
      <View><Text style={ui.label}>Color</Text><Field autoCapitalize="words" placeholder="Optional" value={color} onChangeText={setColor} /></View>
      {error ? <Text style={styles.error}>{error}</Text> : null}
      <Button title={saving ? 'Saving…' : creating ? 'Add car' : 'Save changes'} onPress={save} disabled={saving || year.length !== 4 || !make.trim() || !model.trim()} />
    </Card>
    {!creating ? <Button tone="danger" title="Remove car" onPress={remove} disabled={saving} /> : null}
  </Screen>;
}

const styles = StyleSheet.create({
  heading: { gap: 5, paddingVertical: 4 },
  eyebrow: { color: palette.orange, fontWeight: '900', letterSpacing: 1.2, fontSize: 11 },
  title: { color: palette.ink, fontSize: 29, fontWeight: '900' },
  form: { gap: 15 },
  error: { color: palette.red, fontWeight: '800', lineHeight: 20 },
});
