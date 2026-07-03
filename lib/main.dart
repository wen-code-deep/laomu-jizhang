import 'package:flutter/material.dart';
import 'screens/home_screen.dart';
import 'services/storage_service.dart';
import 'services/ocr_service.dart';
import 'models/expense.dart';

// 百度 OCR API 密钥
const _apiKey = '3frxnDW8dFVDuHf4lBkyyBj0';
const _secretKey = 'dBBaGvFLhsBcZmfdyqTiTlSWLwdcqqNe';

void main() {
  runApp(const LaomuApp());
}

class LaomuApp extends StatelessWidget {
  const LaomuApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: '老母记账',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        colorScheme: ColorScheme.fromSeed(
          seedColor: Colors.orange,
          brightness: Brightness.light,
        ),
        useMaterial3: true,
        fontFamily: 'System',
      ),
      home: const SplashScreen(),
    );
  }
}

/// 启动画面 —— 加载本地数据
class SplashScreen extends StatefulWidget {
  const SplashScreen({super.key});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> {
  final StorageService _storage = StorageService();
  final BaiduOcrService _ocrService =
      BaiduOcrService(apiKey: _apiKey, secretKey: _secretKey);
  bool _loading = true;
  String? _error;
  List<Expense>? _expenses;

  @override
  void initState() {
    super.initState();
    _loadData();
  }

  Future<void> _loadData() async {
    try {
      final expenses = await _storage.loadExpenses();
      if (mounted) {
        setState(() {
          _expenses = expenses;
          _loading = false;
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _error = '加载数据失败：$e';
          _loading = false;
        });
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_loading) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(Icons.account_balance_wallet,
                  size: 80, color: Colors.orange[200]),
              const SizedBox(height: 20),
              const Text(
                '老母记账',
                style: TextStyle(
                    fontSize: 28,
                    fontWeight: FontWeight.bold,
                    color: Colors.orange),
              ),
              const SizedBox(height: 16),
              const CircularProgressIndicator(color: Colors.orange),
            ],
          ),
        ),
      );
    }

    if (_error != null) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.error_outline, size: 64, color: Colors.red),
              const SizedBox(height: 16),
              Text(_error!, style: const TextStyle(color: Colors.red)),
              const SizedBox(height: 16),
              ElevatedButton(
                onPressed: () {
                  setState(() {
                    _loading = true;
                    _error = null;
                  });
                  _loadData();
                },
                child: const Text('重试'),
              ),
            ],
          ),
        ),
      );
    }

    return HomeScreen(
      initialExpenses: _expenses!,
      ocrService: _ocrService,
    );
  }
}
