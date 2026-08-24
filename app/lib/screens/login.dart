import 'package:dio/dio.dart';
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../state/auth.dart';
import '../widgets/aurora.dart';

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
  void dispose() {
    _email.dispose();
    _pw.dispose();
    _nick.dispose();
    super.dispose();
  }

  String _errorText(Object? e) {
    if (e is DioException) {
      final code = e.response?.statusCode;
      if (code == 409) return '이미 가입된 이메일입니다 — "로그인으로"를 눌러 로그인하세요';
      if (code == 401) return '비밀번호가 틀렸습니다';
      if (code == 422) return '입력을 확인하세요 (비밀번호 8자 이상, 이메일 형식)';
      if (e.response == null) return '서버에 연결할 수 없습니다 — 같은 와이파이인지 확인하세요';
    }
    return '실패: 이메일/비밀번호를 확인하세요';
  }

  InputDecoration _dec(String label) => InputDecoration(
      labelText: label,
      labelStyle: const TextStyle(color: Aurora.sub, fontSize: 13.5),
      filled: true, fillColor: Aurora.ink1,
      contentPadding:
          const EdgeInsets.symmetric(horizontal: 14, vertical: 14),
      enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: const BorderSide(color: Aurora.line)),
      focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(15),
          borderSide: const BorderSide(color: Aurora.peri)));

  @override
  Widget build(BuildContext context) {
    final auth = ref.watch(authProvider);
    return Scaffold(
      backgroundColor: Aurora.ink0,
      body: Stack(children: [
        // 숨쉬는 글로우 하나 (부드러운 방사형 빛)
        Positioned(top: 20, left: 0, right: 0, child: Center(child: Container(
            width: 420, height: 420,
            decoration: BoxDecoration(shape: BoxShape.circle,
                gradient: RadialGradient(colors: [
                  Aurora.peri.withValues(alpha: .20),
                  Aurora.rose.withValues(alpha: .07),
                  Colors.transparent,
                ], stops: const [0, .55, 1]))))),
        SafeArea(child: Center(child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(26, 32, 26, 20),
          child: Column(children: [
            // 로고 = 할로 링 (브랜드 심볼과 노출 링이 같은 도형)
            HaloRing(size: 110, progress: .75, stroke: 8,
                center: Container(width: 52, height: 52,
                    decoration: const BoxDecoration(shape: BoxShape.circle,
                        gradient: LinearGradient(
                            colors: [Aurora.peri, Aurora.rose])))),
            const SizedBox(height: 22),
            Row(mainAxisAlignment: MainAxisAlignment.center, children: [
              const GradText('Soft', style: TextStyle(
                  fontSize: 34, fontWeight: FontWeight.w800,
                  letterSpacing: -.5)),
              Text('Reel', style: TextStyle(
                  fontSize: 34, fontWeight: FontWeight.w800,
                  letterSpacing: -.5, color: Colors.white)),
            ]),
            const SizedBox(height: 8),
            const Text('위험한 빛은 줄이고, 감동은 그대로.\n모두의 눈이 편안한 숏폼.',
                textAlign: TextAlign.center,
                style: TextStyle(color: Aurora.sub, fontSize: 13.5,
                    height: 1.6)),
            const SizedBox(height: 30),
            TextField(controller: _email, decoration: _dec('이메일')),
            const SizedBox(height: 10),
            TextField(controller: _pw, obscureText: true,
                decoration: _dec('비밀번호 (8자+)')),
            if (_signup) ...[
              const SizedBox(height: 10),
              TextField(controller: _nick, decoration: _dec('닉네임')),
            ],
            const SizedBox(height: 20),
            if (auth.hasError)
              Padding(padding: const EdgeInsets.only(bottom: 10),
                  child: Text(_errorText(auth.error),
                      style: const TextStyle(
                          color: Aurora.rose, fontSize: 12.5))),
            SizedBox(width: double.infinity, child: AuroraButton(
                label: _signup ? '이메일로 시작하기' : '로그인',
                onTap: auth.isLoading ? null : () {
                  final n = ref.read(authProvider.notifier);
                  _signup
                      ? n.signup(_email.text.trim(), _pw.text,
                          _nick.text.trim())
                      : n.login(_email.text.trim(), _pw.text);
                })),
            TextButton(
                onPressed: () => setState(() => _signup = !_signup),
                child: Text(_signup ? '로그인으로' : '계정이 없나요? 가입',
                    style: const TextStyle(color: Aurora.sub,
                        fontSize: 12.5))),
            const SizedBox(height: 6),
            const Text('계속하면 이용약관과 개인정보 처리방침에 동의하게 됩니다',
                style: TextStyle(fontSize: 10, color: Color(0xFF5E5F73))),
          ]),
        ))),
      ]),
    );
  }
}
