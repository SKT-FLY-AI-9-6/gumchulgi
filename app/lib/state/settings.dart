import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../api/client.dart';
import '../api/models.dart';

class SettingsController extends AsyncNotifier<AppSettings> {
  @override
  Future<AppSettings> build() => ref.read(apiProvider).getSettings();

  Future<void> setFilter(bool on) => _put(
      (s) => s.copyWith(filterOn: on));

  Future<void> setAutoSkip(bool on) => _put(
      (s) => s.copyWith(autoSkip: on));

  Future<void> _put(AppSettings Function(AppSettings) f) async {
    final cur = state.value ??
        const AppSettings(filterOn: true, autoSkip: false);
    final next = f(cur);
    state = AsyncData(next);
    state = AsyncData(await ref.read(apiProvider).putSettings(next));
  }
}

final settingsProvider =
    AsyncNotifierProvider<SettingsController, AppSettings>(
        SettingsController.new);
