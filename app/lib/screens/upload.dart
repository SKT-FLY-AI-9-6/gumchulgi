import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:image_picker/image_picker.dart';

import '../api/client.dart';
import '../theme.dart';

class UploadScreen extends ConsumerStatefulWidget {
  const UploadScreen({super.key});
  @override
  ConsumerState<UploadScreen> createState() => _UploadState();
}

class _UploadState extends ConsumerState<UploadScreen> {
  final _title = TextEditingController();
  XFile? _file;
  double? _progress;
  String? _message;

  @override
  void dispose() {
    _title.dispose();
    super.dispose();
  }

  Future<void> _pick() async {
    final f = await ImagePicker().pickVideo(source: ImageSource.gallery);
    if (!mounted) return;
    if (f != null) setState(() { _file = f; _message = null; });
  }

  Future<void> _upload() async {
    if (_file == null) return;
    setState(() { _progress = 0; _message = null; });
    try {
      await ref.read(apiProvider).upload(_file!, _title.text,
          onProgress: (sent, total) {
            if (mounted) setState(() => _progress = sent / total);
          });
      if (!mounted) return;
      setState(() {
        _progress = null; _file = null; _title.clear();
        _message = '업로드 완료 — 검출·보정 처리 중입니다.\n'
            '완료되면 피드와 내 페이지에 표시됩니다.';
      });
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _progress = null;
        _message = '업로드 실패: 크기(200MB)·길이(3분) 제한을 확인하세요';
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('영상 업로드')),
      body: Padding(padding: const EdgeInsets.all(16), child: Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          OutlinedButton.icon(onPressed: _pick,
              icon: const Icon(Icons.video_library_outlined),
              label: Text(_file == null ? '갤러리에서 영상 선택' : '선택됨: 변경')),
          const SizedBox(height: 12),
          TextField(controller: _title,
              decoration: const InputDecoration(labelText: '제목')),
          const SizedBox(height: 20),
          if (_progress != null)
            LinearProgressIndicator(value: _progress)
          else
            FilledButton(onPressed: _file == null ? null : _upload,
                child: const Text('업로드')),
          if (_message != null)
            Padding(padding: const EdgeInsets.only(top: 16),
                child: Text(_message!,
                    style: const TextStyle(color: AppColors.sub))),
        ])),
    );
  }
}
