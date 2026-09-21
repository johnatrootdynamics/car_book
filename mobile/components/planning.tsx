import DateTimePicker, { DateTimePickerEvent } from '@react-native-community/datetimepicker';
import { useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, Text, View } from 'react-native';

import { Button } from '@/components/ui';
import { palette } from '@/lib/theme';

type PickerMode = 'date' | 'time';

export function NativeDateTimeField({
  label,
  value,
  mode,
  onChange,
  optional = false,
  minimumDate,
}: {
  label: string;
  value: Date | null;
  mode: PickerMode;
  onChange: (value: Date | null) => void;
  optional?: boolean;
  minimumDate?: Date;
}) {
  const [open, setOpen] = useState(false);
  const selected = value || defaultValue(mode, minimumDate);
  const update = (event: DateTimePickerEvent, next?: Date) => {
    if (Platform.OS !== 'ios') setOpen(false);
    if (event.type !== 'dismissed' && next) onChange(next);
  };
  return <View style={styles.fieldGroup}>
    <View style={styles.labelRow}><Text style={styles.label}>{label}</Text>{optional ? <Text style={styles.optional}>Optional</Text> : null}</View>
    <Pressable onPress={() => setOpen(true)} style={({ pressed }) => [styles.pickerButton, pressed && styles.pressed]}>
      <Text style={[styles.pickerValue, !value && styles.placeholder]}>{value ? displayValue(value, mode) : mode === 'date' ? 'Choose a date' : 'Choose a time'}</Text>
      <Text style={styles.chevron}>›</Text>
    </Pressable>
    {optional && value ? <Pressable onPress={() => onChange(null)} style={styles.clearButton}><Text style={styles.clearText}>Clear time</Text></Pressable> : null}
    {open && Platform.OS !== 'ios' ? <DateTimePicker value={selected} mode={mode} minuteInterval={mode === 'time' ? 30 : undefined} minimumDate={minimumDate} onChange={update} /> : null}
    {Platform.OS === 'ios' ? <Modal visible={open} transparent animationType="fade" onRequestClose={() => setOpen(false)}>
      <Pressable style={styles.modalShade} onPress={() => setOpen(false)}>
        <Pressable style={styles.modalCard} onPress={event => event.stopPropagation()}>
          <View style={styles.modalHead}><Text style={styles.modalTitle}>{label}</Text><Pressable onPress={() => setOpen(false)}><Text style={styles.done}>Done</Text></Pressable></View>
          <DateTimePicker value={selected} mode={mode} display={mode === 'date' ? 'inline' : 'spinner'} minuteInterval={mode === 'time' ? 30 : undefined} minimumDate={minimumDate} accentColor={palette.orange} onChange={update} />
          <Button title="Use this selection" onPress={() => setOpen(false)} />
        </Pressable>
      </Pressable>
    </Modal> : null}
  </View>;
}

export function ChoiceChip({ label, selected, onPress }: { label: string; selected: boolean; onPress: () => void }) {
  return <Pressable onPress={onPress} style={({ pressed }) => [styles.chip, selected && styles.chipSelected, pressed && styles.pressed]}><Text style={[styles.chipText, selected && styles.chipTextSelected]}>{label}</Text></Pressable>;
}

function defaultValue(mode: PickerMode, minimumDate?: Date) {
  if (mode === 'date') return minimumDate || new Date();
  const value = new Date();
  value.setHours(9, 0, 0, 0);
  return value;
}

function displayValue(value: Date, mode: PickerMode) {
  return mode === 'date'
    ? value.toLocaleDateString('en-US', { weekday: 'short', month: 'long', day: 'numeric', year: 'numeric' })
    : value.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' });
}

const styles = StyleSheet.create({
  fieldGroup: { gap: 7 }, labelRow: { flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, label: { color: palette.ink, fontSize: 13, fontWeight: '800' }, optional: { color: palette.muted, fontSize: 11, fontWeight: '700' },
  pickerButton: { minHeight: 52, borderRadius: 13, borderWidth: 1, borderColor: '#D0D5DD', backgroundColor: 'white', paddingHorizontal: 15, flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }, pickerValue: { color: palette.ink, fontSize: 15, fontWeight: '700', flex: 1 }, placeholder: { color: '#98A2B3', fontWeight: '500' }, chevron: { color: palette.orange, fontSize: 25, marginLeft: 10 },
  clearButton: { alignSelf: 'flex-start', paddingVertical: 2 }, clearText: { color: palette.orange, fontSize: 12, fontWeight: '800' }, pressed: { opacity: .65 },
  modalShade: { flex: 1, justifyContent: 'flex-end', backgroundColor: 'rgba(15, 23, 42, .42)' }, modalCard: { backgroundColor: palette.surface, borderTopLeftRadius: 26, borderTopRightRadius: 26, padding: 18, paddingBottom: 34, gap: 12 }, modalHead: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center' }, modalTitle: { color: palette.ink, fontSize: 19, fontWeight: '900' }, done: { color: palette.orange, fontWeight: '900' },
  chip: { minHeight: 40, borderRadius: 999, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white', paddingHorizontal: 14, alignItems: 'center', justifyContent: 'center' }, chipSelected: { borderColor: palette.orange, backgroundColor: palette.orangeSoft }, chipText: { color: palette.muted, fontSize: 13, fontWeight: '800' }, chipTextSelected: { color: '#C2410C' },
});
