import 'dart:io';
import 'package:path_provider/path_provider.dart';
import '../models/expense.dart';

/// 本地文件存储服务
/// 把支出数据以 JSON 格式保存在手机/电脑本地
class StorageService {
  static const String _fileName = 'expenses.json';

  /// 获取存储文件的完整路径
  Future<File> _getFile() async {
    final dir = await getApplicationDocumentsDirectory();
    return File('${dir.path}/$_fileName');
  }

  /// 保存支出列表到本地文件
  Future<void> saveExpenses(List<Expense> expenses) async {
    final file = await _getFile();
    final jsonStr = Expense.listToJson(expenses);
    await file.writeAsString(jsonStr);
  }

  /// 从本地文件读取支出列表
  /// 如果文件不存在，返回空列表
  Future<List<Expense>> loadExpenses() async {
    try {
      final file = await _getFile();
      if (await file.exists()) {
        final jsonStr = await file.readAsString();
        if (jsonStr.isEmpty) return [];
        return Expense.listFromJson(jsonStr);
      }
    } catch (e) {
      // 读取失败时返回空列表，避免 App 崩溃
    }
    return [];
  }
}
