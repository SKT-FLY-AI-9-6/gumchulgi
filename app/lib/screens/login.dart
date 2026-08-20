import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/auth.dart';
import '../theme.dart';

class LoginScreen extends ConsumerStatefulWidget {
  const LoginScreen({super.key});
  @override
  ConsumerState<LoginScreen> createState() => _LoginState();
}

class _LoginState extends ConsumerState<LoginScreen> {
  final _email = TextEditingController();
  final _pw = TextEditingController();
  final _nick = TextEditingController();
  bool _signup = false;

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      body: Center(child: SingleChildScrollView(
        padding: const EdgeInsets.all(32),
        child: Column(children: [
          const Text('검출기', style: TextStyle(
              fontSize: 32, fontWeight: FontWeight.bold)),
          const Text('광과민성 안전 숏폼 플랫폼',
              style: TextStyle(color: AppColors.sub)),
          const SizedBox(height: 32),
          TextField(controller: _email, decoration:
              const InputDecoration(labelText: '이메일')),
          TextField(controller: _pw, obscureText: true,
              decoration: const InputDecoration(labelText: '비밀번호 (8자+)')),
          if (_signup)
            TextField(controller: _nick, decoration:
                const InputDecoration(labelText: '닉네임')),
          const SizedBox(height: 24),
          if (auth.hasError)
            Padding(padding: const EdgeInsets.only(bottom: 8),
                child: Text('실패: 이메일/비밀번호를 확인하세요',
                    style: const TextStyle(color: AppColors.red))),
          FilledButton(
            onPressed: auth.isLoading ? null : () {
              final n = ref.read(authProvider.notifier);
              _signup
                  ? n.signup(_email.text.trim(), _pw.text, _nick.text.trim())
                  : n.login(_email.text.trim(), _pw.text);
            },
            child: Text(_signup ? '가입하기' : '로그인')),
          TextButton(
            onPressed: () => setState(() => _signup = !_signup),
            child: Text(_signup ? '로그인으로' : '계정이 없나요? 가입')),
        ]),
      )),
    );
  }
}
