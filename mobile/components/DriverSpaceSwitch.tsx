import { SymbolView } from 'expo-symbols';
import { useRef } from 'react';
import { PanResponder, Pressable, StyleSheet, Text, View } from 'react-native';

import { palette } from '@/lib/theme';

export type DriverSpace = 'track' | 'social';

const spaces: { value: DriverSpace; label: string; symbol: string }[] = [
  { value: 'track', label: 'Track', symbol: 'flag.checkered' },
  { value: 'social', label: 'Social', symbol: 'person.2.fill' },
];

export function DriverSpaceSwitch({ active, onChange, compact = false }: { active: DriverSpace; onChange: (space: DriverSpace) => void; compact?: boolean }) {
  const activeRef = useRef(active);
  const onChangeRef = useRef(onChange);
  activeRef.current = active;
  onChangeRef.current = onChange;

  const isHorizontalSwipe = (_: unknown, gesture: { dx: number; dy: number }) => Math.abs(gesture.dx) > 12 && Math.abs(gesture.dx) > Math.abs(gesture.dy) * 1.35;

  const panResponder = useRef(PanResponder.create({
    onMoveShouldSetPanResponder: isHorizontalSwipe,
    onMoveShouldSetPanResponderCapture: isHorizontalSwipe,
    onPanResponderRelease: (_, gesture) => {
      if (Math.abs(gesture.dx) < 42 || Math.abs(gesture.dx) < Math.abs(gesture.dy) * 1.25) return;
      if (gesture.dx < 0 && activeRef.current === 'track') onChangeRef.current('social');
      if (gesture.dx > 0 && activeRef.current === 'social') onChangeRef.current('track');
    },
    onPanResponderTerminationRequest: () => true,
  })).current;

  return <View style={[styles.wrap, compact && styles.compactWrap]}>
    <View style={[styles.switch, compact && styles.compactSwitch]} {...panResponder.panHandlers}>
      {spaces.map(space => {
        const selected = active === space.value;
        return <Pressable
          key={space.value}
          accessibilityRole="tab"
          accessibilityState={{ selected }}
          accessibilityLabel={`${space.label} space`}
          onPress={() => onChange(space.value)}
          style={({ pressed }) => [styles.option, compact && styles.compactOption, selected && styles.optionActive, pressed && styles.pressed]}
        >
          <SymbolView name={{ ios: space.symbol, android: space.symbol, web: space.symbol } as any} tintColor={selected ? 'white' : palette.muted} size={17} />
          <Text style={[styles.label, selected && styles.labelActive]}>{space.label}</Text>
        </Pressable>;
      })}
    </View>
    {!compact ? <Text style={styles.hint}>Tap or swipe to switch spaces</Text> : null}
  </View>;
}

const styles = StyleSheet.create({
  wrap: { gap: 6 },
  compactWrap: { flex: 1, gap: 0 },
  switch: { flexDirection: 'row', minHeight: 46, padding: 4, borderRadius: 15, borderWidth: 1, borderColor: palette.line, backgroundColor: 'white' },
  compactSwitch: { minHeight: 42, borderRadius: 14 },
  option: { flex: 1, minHeight: 38, borderRadius: 11, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 7 },
  compactOption: { minHeight: 34, borderRadius: 10 },
  optionActive: { backgroundColor: palette.navy },
  label: { color: palette.muted, fontSize: 13, fontWeight: '900' },
  labelActive: { color: 'white' },
  hint: { color: palette.muted, fontSize: 10, fontWeight: '600', textAlign: 'center' },
  pressed: { opacity: .68 },
});
