import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'screens/login.dart';
import 'screens/shell.dart';
import 'state/auth.dart';
import 'theme.dart';

void main() => runApp(const ProviderScope(child: App()));

class App extends ConsumerWidget {
  const App({super.key});
  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authProvider);
    return MaterialApp(
      title: '검출기', theme: appTheme,
      home: auth.when(
        data: (u) => u == null ? const LoginScreen() : const ShellScreen(),
        loading: () => const Scaffold(
            body: Center(child: CircularProgressIndicator())),
        error: (_, __) => const LoginScreen()));
  }
}
