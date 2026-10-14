-- loosechange:// handler. The installer replaces __RUNNER__ and compiles this into
-- ~/Applications/loosechange.app with the URL scheme registered in Info.plist.
-- Every link is checked first; nothing is written without the user's click.
property runnerPath : "__RUNNER__"

on open location theURL
	activate
	try
		set r to do shell script "/bin/bash " & quoted form of runnerPath & " check " & quoted form of theURL without altering line endings
	on error errMsg
		display alert "loosechange" message errMsg as critical
		return
	end try
	set statusText to my firstLine(r)
	set msg to my restOf(r)
	if statusText is "ERROR" then
		display alert "loosechange" message msg as warning
		return
	end if
	if statusText is "DONE" then
		display dialog msg buttons {"OK"} default button 1 with title "loosechange" with icon note
		return
	end if
	if statusText is "ASK_RESTART" then
		set okLabel to "Закрыть VibeForge и установить"
		set runMode to "apply-restart"
	else
		set okLabel to "Установить"
		set runMode to "apply"
	end if
	try
		display dialog msg buttons {"Отмена", okLabel} default button okLabel cancel button "Отмена" with title "loosechange" with icon note
	on error number -128
		return
	end try
	set r2 to do shell script "/bin/bash " & quoted form of runnerPath & " " & runMode & " " & quoted form of theURL without altering line endings
	if my firstLine(r2) is "DONE" then
		display dialog my restOf(r2) buttons {"OK"} default button 1 with title "loosechange" with icon note
	else
		display alert "loosechange" message my restOf(r2) as warning
	end if
end open location

on firstLine(t)
	set ps to paragraphs of t
	if (count of ps) is 0 then return ""
	return item 1 of ps
end firstLine

on restOf(t)
	set ps to paragraphs of t
	if (count of ps) < 2 then return ""
	set AppleScript's text item delimiters to linefeed
	set out to (items 2 thru -1 of ps) as text
	set AppleScript's text item delimiters to ""
	return out
end restOf

on run
	display dialog "Обработчик ссылок loosechange:// установлен. В боте нажимайте «⚡ Установить в один клик»." buttons {"OK"} default button 1 with title "loosechange"
end run
