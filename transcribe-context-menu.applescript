on run {input, parameters}
	set audioExtensions to {"mp3", "wav", "m4a", "ogg"}

	repeat with f in input
		set filePath to POSIX path of f
		set fileName to do shell script "basename " & quoted form of filePath
		set fileExt to do shell script "echo " & quoted form of fileName & " | sed 's/.*\\.//' | tr '[:upper:]' '[:lower:]'"

		if audioExtensions contains fileExt then
			display notification "Starting: " & fileName with title "Transcribe" sound name "Tink"

			try
				set shellCmd to "export PATH=/opt/homebrew/bin:$PATH && /usr/bin/python3 '/Users/vitalijfateicev/Projects/TranscribeAGENT/transcribe.py' " & quoted form of filePath & " 2>&1"
				do shell script shellCmd

				set txtPath to do shell script "echo " & quoted form of filePath & " | sed 's/\\.[^.]*$/.txt/'"
				set wordCount to do shell script "wc -w < " & quoted form of txtPath & " | tr -d ' '"

				display notification wordCount & " words → " & fileName with title "Transcription Complete ✓" sound name "Glass"
			on error errMsg
				display notification errMsg with title "Transcription Error" sound name "Basso"
			end try
		end if
	end repeat

	return input
end run
