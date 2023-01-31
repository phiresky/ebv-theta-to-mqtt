#########################################################################
#
# Modifizierte Version die sowohl die Raumstation Gamma 10 und 30 
# unterstützt. Basiert auf der Version vom User heiko322 zu finden 
# unter der URL https://forum.fhem.de/index.php/topic,35720.0.html
# Das Protokoll der Gamma 30 hat eine ähliche Struktur und die gleiche
# Checksumme, aber andere Nachrichten. Für das Protokoll der Gamma 10:
# https://github.com/bogeyman/gamma
#
#########################################################################
# fhem Modul für EBV Heinzungsregler, im speziellen zum Mithören und 
# Auswerten des RS485 Datenverkehrs zwischen Regler und Raumstation. 
# Das Modul wurde auf Grundlage der Raumstation Gamma RS 30 entwickelt, 
# die mit einer Rotex Gas-Solor-Unit GSU 528 verbunden ist. 
# Eine Rückmeldung mit welchen weiteren Reglern und Raumstationen das
# Modul funktioniert wäre wünschenswert und könnte die Anwenderbasis 
# erweitern.
# Als Basis diente das Modul 00_WHR962.pm
#
# Da das Datenprotokol unprotokoliert ist folgen nun einige Hinweise und
# meine bisherigen Entschlüsselungsversuche: 
# Der Serial-Port wird auf 9600, 8 Bits, 1 Stopbit, Keine Flusskontrolle,  
# keine Parität eingestellt, wobei wohl nur die Baudrate relevant ist.
# Die einzelnen Sequenzen im Sendefluss haben eine CRC16 Checksumme vom 
# Typ RC-CCITT Kermit (width=16 poly=0x1021 init=0x0000 refin=true 
# refout=true xorout=0x0000 check=0x2189 name="KERMIT"). 
# Zum Testen: http://www.lammertbies.nl/comm/info/crc-calculation.html .
# Die komplette Sequenz wird ziemlich genau 4x pro Minute gesendet. 
# Startbyte ist 0x82, davor liegt 0x06 oder 0x41 bzw. eine Folge dieser
# beiden Bytes. Das Schlussbyte ist 0x03. Davor befinden sich 2 Bytes
# welche die CRC16 Checksumme der Sequenz beginnend nach dem Startbyte
# bis zur Checksumme bilden. Es folgt eine vollständige Datenfolge zur
# Verdeutlichung: 
#410641 82 60 20 01 21 F1 D1A8 03 06
#410641 82 60 20 10 21 01020238000000000000000000000000 A944 03 06 424242C3C3C3444444C5C5C5C6C6C6474747484848
#410641 82 60 20 01 21 F2 4A9A 03 06
#410641 82 60 20 10 21 00000000000000000000000000000000 ED5A 03 06
#410641 82 60 20 01 21 F3 C38B 03 06
#410641 82 60 10 01 21 09 E49F 03 06
#       82 41 20 09 21 032B243908DB080D12 4C2A 03
#410641 82 60 20 01 21 F4 7CFF 03 06
#410641 82 60 10 01 21 09 E49F 03 06 
#       82 41 20 09 21 040CF6FB3C0B310100 26A4 03
#410641 82 60 20 01 21 F5 F5EE 03 06
#410641 82 60 10 01 21 09 E49F 03 06 
#       82 41 20 09 21 056400B31194119407 C1AB 03
#410641 82 60 20 01 21 F6 6EDC 03 06
#410641 82 60 10 01 21 09 E49F 03 06 
#       82 41 20 09 21 069E640A020AFF2500 CE93 03 424242C3C3C3444444C5C5C5C6C6C6474747484848 D1D1D16060601D1D1D1E1E1E9F9F9FD1D1D1D2D2D2535353D4D4D4555555565656D7D7D7D8D8D85959595A5A5ADBDBDB5C5C5CDDDDDDDEDEDE5F5F5F
# Nach Byte 0x21 folgen die eigentlichen Daten. Das Byte davor scheint
# die Länge der Daten anzugeben. Wiederrum davor steht vermutlich die 
# Adressierung und die Art der Sequenz. Das konnte ich bisher noch nicht
# entziffern. 
# Die Daten, die ich bisher zuordnen konnte befinden sich im obigen
# Beispiel in Zeile 7 und dort wie bereits erwähnt nach 0x21: 
# 032B243908 -> 0x03 ist die Funktion/Register?, 0x2B=43 ist die
# Vorlauftemperatur, 0x24=36 ist die Rücklauftemperatur, 0x39=57 ist
# die Temperatur des Warmwassers und 0x08=8 ist die Außentemperatur.
# Diese Werte stammen vom Heizkessel. In Zeile 2 befinden sich die 
# Soll-Werte die von der Steuerung kommen: Das zweite 0x02 ist der 
# Soll-Zustand (2 = HK ein/WW aus; 0 = HK aus/WW aus; 3 = HK ein/
# WW ein; 1 = HK aus/WW ein) und 0x38=56 ist die Soll-Vorlauftemperatur. 
# Dann noch gegen Ende der Sequenz in Zeile 10: 0x01 gibt den 
# Betriebszustand des Kessels aus (Bedeutung der Zahlen siehe Anleitung
# oder hier direkt im Code). 
																		# Kommentarbereich
package main;

use strict;                          #
use warnings;                        #

my $missingModulDigest = "";

eval "use Digest::CRC;1" or $missingModulDigest = "Digest::CRC ";

sub EBV_Read($);                  #
sub EBV_Ready($);                 #

my $Readpart = "";   # Hilfsvariable für auslesen des Puffers. Warum muss die hier stehen? 
					 # bei Definition in der Read-Funktion funktioniert das Modul nicht.


#########################################################################

sub EBV_Initialize($)
{
	my ($hash) = @_;

	require "$attr{global}{modpath}/FHEM/DevIo.pm";

	$hash->{ReadFn}  = "EBV_Read";
	$hash->{ReadyFn} = "EBV_Ready";
	$hash->{DefFn}   = "EBV_Define";
	$hash->{UndefFn} = "EBV_Undef";
	$hash->{AttrList} =
	  "do_not_notify:1,0 " . $readingFnAttributes;
}

#########################################################################									#

sub EBV_Define($$)
{
	my ( $hash, $def ) = @_;
	my @a = split( "[ \t][ \t]*", $def );

	return "wrong syntax: define <name> EBV [devicename|none]"
	  if ( @a != 3 );

	DevIo_CloseDev($hash);
	my $name = $a[0];
	my $dev  = $a[2];

	if ( $dev eq "none" )
	{
		Log3 undef, 1, "EBV device is none, commands will be echoed only";
		return undef;
	}

	$hash->{DeviceName} = $dev;
	my $ret = DevIo_OpenDev( $hash, 0, "" );

	if ($missingModulDigest) {
		my $msg = "Modul functionality limited because of missing perl modules: " . $missingModulDigest;
		Log3 undef, 1, $msg;
		$hash->{PERL} = $msg;
	}
	return $ret;
}

#########################################################################

sub                   
  EBV_Undef($$)    
{                   
	my ( $hash, $arg ) = @_;    
	DevIo_CloseDev($hash);      
	RemoveInternalTimer($hash); 
	return undef;               
}    

#########################################################################

sub
EBV_crc16Kermit($) {
  my ($raw)= pack("H*" ,@_);
  my $ctx= Digest::CRC->new(width=>16, init=>0x0000, xorout=>0x0000,
                          refout=>1, poly=>0x1021, refin=>1, cont=>1);
  $ctx->add($raw);
  my $crc = $ctx->hexdigest;
  return lc(substr($crc,2,2).substr($crc,0,2));
}

sub EBV_checkCrc16Kermit($$) {
	my ($hash,$omsg) = @_;
	my $name = $hash->{NAME};
	if ($missingModulDigest) {
		Log3 $name, 5, "EBV_checkCrc16Kermit: $missingModulDigest not installed, no check for $omsg";
		return 1;
	}
	my $msgcrc = substr($omsg,-4);
	my $msg = substr($omsg,0,-4);
	my $crc = EBV_crc16Kermit($msg);
	my $equal = ($msgcrc eq $crc);
	Log3 $name, 5, "EBV_checkCrc16Kermit: equal=$equal crc=$crc msg=$msg $msgcrc";
	return $equal;
}

#########################################################################

# called from the global loop, when the select for hash->{FD} reports data
sub EBV_Read($)
{
	my ($hash) = @_;
	my $name = $hash->{NAME};
	my $buf = DevIo_SimpleRead($hash);
	my $Complete = "";  # Hilfsvariable für komplette Sequenz
	
	###### Daten der seriellen Schnittstelle holen, in Hex umwandeln, und an $Readpart anhaengen
	return "" if ( !defined($buf) );
	$buf = unpack( 'H*', $buf );
	$Readpart .= $buf;
	#Log3 $name, 5, "Current buffer content: " . $Readpart;

	###### 	Datensätze in Variablen aus der kompletten Sequenz übertragen
	if ( $Readpart =~ /dddddddedede5f5f5f/i || $Readpart =~ /1d1d1d1d1d1e1e1e1e1e9f9f9f9f9f/i)    # wenn im Puffer die Endsequenz vorkommt
	{
		$Complete = $Readpart; 
		$Readpart = "";  # Puffer löschen
		Log3 $name, 5, "Komplette Sequenz: " . $Complete;

		###### Gamma 10 Station
		if ( $Complete =~ /ff8210202004/i && $Complete =~ /1d1d1d1d1d1e1e1e1e1e9f9f9f9f9f/i)
		{
			###### Position der Datensätze ermitteln
			# Kommen auch ohne Raumstation
                        my $test1 = index( $Complete, "8210202004" ) ;
			# Kommt nur mit Raumstation
                        my $test2 = index( $Complete, "8210204002" ) ;
			if ($test2 != -1) {
				# Es ist eine Raumstation angeschlossen
			}
 			###### Relevante Daten extrahieren 
			my $buf1 = substr( $Complete, $test1 + 2 , 76 );
			if(!EBV_checkCrc16Kermit($hash, $buf1)) {
				Log3 $name, 3, "EBV_Read: CRC error!";
				$Readpart = "";
				return "";
			}
			$buf1 = substr( $buf1, 4 );
			my $Aussentemp = substr( $buf1, 2*2, 2 ); 
			$Aussentemp = (hex($Aussentemp)/2) - 52;
			my $Kesseltemp = substr( $buf1, 32*2, 2 ); 
			$Kesseltemp = (hex($Kesseltemp)/2);
			my $KesseltempSoll = substr( $buf1, 17*2, 2 ); 
			$KesseltempSoll = (hex($Kesseltemp)/2);
			my $Warmwasser = substr( $buf1, 8*2, 2 ); 
			$Warmwasser = (hex($Warmwasser)/2);
			my $Vorlauftemp = substr( $buf1, 11*2, 2 ); 
			$Vorlauftemp = (hex($Vorlauftemp)/2);
			
			Log3 $name, 4, "Aussentemp: $Aussentemp" ;
			Log3 $name, 4, "Kesseltemp: $Kesseltemp" ;
			Log3 $name, 4, "KesseltempSoll: $KesseltempSoll" ;
			Log3 $name, 4, "Warmwasser: $Warmwasser" ;
			Log3 $name, 4, "Vorlauftemp: $Vorlauftemp" ;
			###### in die READINGS schreiben
			readingsBeginUpdate($hash);
			readingsBulkUpdate( $hash, "Aussentemp",  $Aussentemp );
			readingsBulkUpdate( $hash, "Kesseltemp",  $Kesseltemp );
			if ( $Kesseltemp > 0 ) {
				readingsBulkUpdate( $hash, "KesseltempSoll",  $KesseltempSoll );
			}
			readingsBulkUpdate( $hash, "Warmwasser",  $Warmwasser );
			readingsBulkUpdate( $hash, "Vorlauftemp",  $Vorlauftemp );
			readingsEndUpdate( $hash, 1 );
		}
		###### Gamma 30 Station
		###### Überpüfen ob die Sequenz komplett war (Anfang und Ende vorhanden)
		if ( $Complete =~ /8260200121f1/i && $Complete =~ /dddddddedede5f5f5f/i)
		{   
			###### Position der Datensätze ermitteln
			my $test1 = index( $Complete, "826020102101" ) ;
			my $test3 = index( $Complete, "824120092103" ) ;
			my $test4 = index( $Complete, "824120092104" ) ;
			###### Relevante Daten extrahieren
			my $buf1 = substr( $Complete, $test1 + "14" , "4" ) ;
			my $buf3 = substr( $Complete, $test3 + "12" , "16" ) ;
			my $buf4 = substr( $Complete, $test4 + "12" , "16" ) ;
			
			my $Vorlauf = substr( $buf3, 0, 2 ); 
			my $Ruecklauf = substr( $buf3, 2, 2 ); 
			my $Aussentemp = substr( $buf3, 6, 2 ); 
			my $Warmwasser = substr( $buf3, 4, 2 ); 
			my $Betriebszustand = substr( $buf4, 12, 2 );   
			$Vorlauf = ( hex($Vorlauf) ) ; 
			$Ruecklauf = ( hex($Ruecklauf) ) ; 
			$Aussentemp = ( hex($Aussentemp) ) ; 
			if ( hex($Warmwasser) != 0 ) {
			  $Warmwasser = ( hex($Warmwasser) ) ; } 
			$Betriebszustand = ( hex($Betriebszustand) ) ; 
			my $Soll_Status = ( hex(substr( $buf1, 0, 2 ) ) ); 
			my $Soll_Vorlauf = ( hex(substr( $buf1, 2, 2 ) ) ); 
			my $Heizkreis = ""; 
			my $WWLadung = ""; 
			my $Soll_Status_Text = ""; 
			if ( $Soll_Status == 2 ) {
				$Soll_Status_Text = "HK ein, WW aus" ; }
			elsif ( $Soll_Status == 0 ) { 
				$Soll_Status_Text = "HK aus, WW aus" ; } 
			elsif ( $Soll_Status == 3 ) { 
				$Soll_Status_Text = "HK ein, WW ein" ; }
			elsif ( $Soll_Status == 1 ) { 
				$Soll_Status_Text = "HK aus, WW ein" ; }	
			else {$Soll_Status_Text = "Unbekannt" ; }
			my $Betriebszustand_Text = ""; 
			if ( $Betriebszustand == 4 ) {
				$WWLadung = "ein" ; }
			else {$WWLadung = "aus" ; }
			if ( $Betriebszustand > 0 && $Betriebszustand < 7 ) {
				$Heizkreis = "ein" ; }
			else {$Heizkreis = "aus" ; }
			if ( $Betriebszustand == 0 ) { 
				$Betriebszustand_Text = "Ruhelage" ;} 
			elsif ( $Betriebszustand == 1 ) { 
				$Betriebszustand_Text = "Belüften" ;}  
			elsif ( $Betriebszustand == 2 ) { 
				$Betriebszustand_Text = "Zündung" ;}  
			elsif ( $Betriebszustand == 3 ) { 
				$Betriebszustand_Text = "Heizen" ;}  
			elsif ( $Betriebszustand == 4 ) { 
				$Betriebszustand_Text = "Warmwasser" ;}  
			elsif ( $Betriebszustand == 5 ) { 
				$Betriebszustand_Text = "Warten" ;}  
			elsif ( $Betriebszustand == 6 ) { 
				$Betriebszustand_Text = "Brenner aus" ;}  
			elsif ( $Betriebszustand == 7 ) { 
				$Betriebszustand_Text = "Pumpennachlauf" ;}  
			### genau: Pumpennachlauf Heizung
			elsif ( $Betriebszustand == 8 ) { 
				$Betriebszustand_Text = "Pumpennachlauf" ;} 
			### genau: Pumpennachlauf Warmwasser				
			else { 
				$Betriebszustand_Text = "Error - please check" ;} 
			Log3 $name, 4, "Warmwasser: $Warmwasser" ;
			Log3 $name, 4, "Vorlauf: $Vorlauf" ;
			Log3 $name, 4, "Soll-Vorlauf: $Soll_Vorlauf" ;
			Log3 $name, 4, "Rücklauf: $Ruecklauf" ;
			Log3 $name, 4, "Außentemperatur: $Aussentemp" ;
			Log3 $name, 4, "Soll-Status: $Soll_Status" ;
			Log3 $name, 4, "Betriebszustand: $Betriebszustand_Text" ;
			
			###### in die READINGS schreiben
			readingsBeginUpdate($hash);
			readingsBulkUpdate( $hash, "Vorlauf",    $Vorlauf );
			readingsBulkUpdate( $hash, "Rücklauf",  $Ruecklauf );
			readingsBulkUpdate( $hash, "AußenTemp", $Aussentemp );
			readingsBulkUpdate( $hash, "WasserTemp", $Warmwasser );
			readingsBulkUpdate( $hash, "Soll-Status", $Soll_Status_Text );
			readingsBulkUpdate( $hash, "Soll-Vorlauf", $Soll_Vorlauf );
			readingsBulkUpdate( $hash, "Heizkreis",  $Heizkreis );
			readingsBulkUpdate( $hash, "Warmwasser",  $WWLadung );
			readingsBulkUpdate( $hash, "Betriebszustand",  $Betriebszustand_Text );
			readingsEndUpdate( $hash, 1 );
		}
	}
	###### Lösche Puffer wenn zu groß, im Falle fehlerhafter Kommunikation
	if ( length ($Readpart) > 2000 ) {
		$Readpart = ""; 
	}
}

#########################################################################

sub EBV_Ready($)
{
	my ($hash) = @_;

	return DevIo_OpenDev( $hash, 1, undef )
	  if ( $hash->{STATE} eq "disconnected" );

	# This is relevant for windows/USB only
	my $po = $hash->{USBDev};
	my ( $BlockingFlags, $InBytes, $OutBytes, $ErrorFlags ) = $po->status;
	return ( $InBytes > 0 );
}

1;

=pod
=begin html

<a name="EBV"></a>
<h3>EBV</h3>
<ul>
  This FHEM module is able to monitor and decrypt the RS485 communication between 
  an EBV Room Station and the heating control unit.<br>
  It is tested with the Room Station Gamma RS30 and a Rotex GSU 528 condensing 
  boiler.<br>
  FHEM can be connected by an USB to RS485 dongle directly to the data bus. 
  <br>
  Note: this module requires the Device::SerialPort or Win32::SerialPort module.
  <br><br>

  <a name="EBVdefine"></a>
  <b>Define</b>
  <ul>
    <code>define &lt;name&gt; EBV &lt;serial-device-name&gt;</code><br>
	Note: Serial baut rate should be 9600 bits per second. 
    <br><br>
    Example:
    <ul>
      <code>define myBoiler EBV /dev/ttyUSB0@9600</code><br>
    </ul>
  </ul>
  <br>

=end html
=cut

