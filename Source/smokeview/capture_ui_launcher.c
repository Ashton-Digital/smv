#ifdef _WIN32
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

int WINAPI wWinMain(HINSTANCE instance, HINSTANCE previous, PWSTR command_line, int show){
  wchar_t directory[MAX_PATH], script[MAX_PATH], arguments[2 * MAX_PATH + 16];
  wchar_t *separator;
  HINSTANCE result;
  DWORD length;

  (void)instance;
  (void)previous;
  (void)show;
  length = GetModuleFileNameW(NULL, directory, MAX_PATH);
  if(length == 0 || length >= MAX_PATH)return 1;
  separator = wcsrchr(directory, L'\\');
  if(separator == NULL)return 1;
  *separator = 0;
  if(swprintf_s(script, MAX_PATH, L"%ls\\capture_slices_ui.pyw", directory) < 0)return 1;
  if(swprintf_s(arguments, 2 * MAX_PATH + 16, L"-3 \"%ls\" %ls", script,
                command_line == NULL ? L"" : command_line) < 0)return 1;

  result = ShellExecuteW(NULL, L"open", L"pyw.exe", arguments, directory, SW_SHOWNORMAL);
  if((INT_PTR)result <= 32){
    result = ShellExecuteW(NULL, L"open", L"pythonw.exe", arguments + 3, directory, SW_SHOWNORMAL);
  }
  if((INT_PTR)result <= 32){
    MessageBoxW(NULL,
                L"Install Python 3.10 or newer with the Python Launcher and Tkinter, then open Capture result slices again.",
                L"Ashton Smokeview", MB_OK | MB_ICONERROR);
    return 1;
  }
  return 0;
}
#endif
