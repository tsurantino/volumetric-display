use std::sync::{Arc, Mutex};
use std::net::{SocketAddr, UdpSocket};
use std::time::Duration;
use tokio::time::interval;
use tokio::sync::mpsc; // For channels between MIDI callback and MIDI processing task

use midir::{MidiInput, MidiOutput, Ignore, MidiOutputConnection, MidiInputPort, MidiOutputPort};
use rosc::{OscPacket, OscMessage, OscType, encoder, decoder::decode_udp};
use tracing::{info, warn, error, Level};
use tracing_subscriber::FmtSubscriber;
use clap::Parser; // For argument parsing

// --- Constants from Python script ---
const NUM_ROWS: usize = 8;
const NUM_COLS: usize = 8;
const NUM_LFO_BANKS: usize = 4;
const NUM_EFFECT_BANKS: usize = 4;
const TOTAL_ROWS: usize = NUM_ROWS * NUM_LFO_BANKS;
const TOTAL_COLS: usize = NUM_COLS * NUM_EFFECT_BANKS;

// APC MINI LED Velocities
const LED_OFF: u8 = 0;
const LED_GREEN: u8 = 1;
const LED_RED: u8 = 3;
const LED_ORANGE: u8 = 5;
const LED_BLUE_ISH: u8 = 6;

// OSC Buffer Size
const OSC_BUF_SIZE: usize = 1536; // A common buffer size for OSC over UDP

lazy_static::lazy_static! {
    static ref NOTE_GRID: [[u8; NUM_COLS]; NUM_ROWS] = {
        let mut grid = [[0u8; NUM_COLS]; NUM_ROWS];
        for r in 0..NUM_ROWS {
            for c in 0..NUM_COLS {
                grid[r][c] = ((NUM_ROWS - 1 - r) * 8 + c) as u8;
            }
        }
        grid
    };
}

// --- Command Line Arguments ---
#[derive(Parser, Debug)]
#[clap(author, version, about, long_about = None)]
struct CliArgs {
    #[clap(long, default_value = "127.0.0.1")]
    in_host: String,
    #[clap(long, default_value_t = 9000)]
    in_port: u16,
    #[clap(long, default_value = "127.0.0.1")]
    out_host: String,
    #[clap(long, default_value_t = 9001)]
    out_port: u16,
}

// --- Shared Application State ---
struct AppState {
    current_lfo_bank: usize,
    current_effect_bank: usize,
    mapping: Vec<Vec<bool>>, // [actual_row][actual_col]
    fader_override_active: Vec<Vec<bool>>, // [lfo_bank_idx][actual_col_idx]
    fader_override_value: Vec<Vec<f32>>,  // [lfo_bank_idx][actual_col_idx]
    latest_lfo_values: Vec<f32>, // [actual_lfo_row_idx]
}

impl AppState {
    fn new() -> Self {
        AppState {
            current_lfo_bank: 0,
            current_effect_bank: 0,
            mapping: vec![vec![false; TOTAL_COLS]; TOTAL_ROWS],
            fader_override_active: vec![vec![false; TOTAL_COLS]; NUM_LFO_BANKS],
            fader_override_value: vec![vec![0.0; TOTAL_COLS]; NUM_LFO_BANKS],
            latest_lfo_values: vec![0.0; TOTAL_ROWS],
        }
    }
}

// Define a common error type for the application
type AppError = Box<dyn std::error::Error + Send + Sync>;

// --- Main Application ---
#[tokio::main]
async fn main() -> Result<(), AppError> { // Use AppError
    let subscriber = FmtSubscriber::builder().with_max_level(Level::DEBUG).finish();
    tracing::subscriber::set_global_default(subscriber).expect("Setting default subscriber failed");
    
    let args = CliArgs::parse();
    info!("Starting ArtNet Mapper in Rust with args: {:?}", args);

    let app_state = Arc::new(Mutex::new(AppState::new()));

    let osc_in_addr_str = format!("{}:{}", args.in_host, args.in_port);
    let osc_out_addr_str = format!("{}:{}", args.out_host, args.out_port);
    
    let osc_out_addr: SocketAddr = osc_out_addr_str.parse().map_err(AppError::from)?;
    let osc_in_addr: SocketAddr = osc_in_addr_str.parse().map_err(AppError::from)?;

    let midi_out_conn = match setup_midi_output() {
        Ok(conn) => Arc::new(Mutex::new(conn)),
        Err(e) => {
            error!("Failed to setup MIDI output: {}. LED feedback will be disabled.", e);
            return Err(e.into()); // Convert String error to AppError
        }
    };
    
    {
        let mut initial_midi_out = midi_out_conn.lock().unwrap();
        clear_all_leds(&mut initial_midi_out);
        let state = app_state.lock().unwrap();
        _update_bank_select_leds(&mut initial_midi_out, &state);
        _refresh_grid_leds(&mut initial_midi_out, &state);
        info!("Initial LED states set.");
    }

    let osc_input_task = tokio::spawn(handle_osc_input(Arc::clone(&app_state), osc_in_addr));
    let (midi_tx, midi_rx) = mpsc::channel(32);
    let midi_input_setup_task = tokio::spawn(keep_midi_input_alive(midi_tx));
    let midi_processing_task = tokio::spawn(process_midi_messages(Arc::clone(&app_state), midi_rx, Arc::clone(&midi_out_conn)));
    let osc_sender_task = tokio::spawn(osc_sender_loop(Arc::clone(&app_state), osc_out_addr));

    info!("OSC Input: {}", osc_in_addr);
    info!("OSC Output: {}", osc_out_addr);
    info!("Control mapper running...");

    match tokio::try_join!(
        osc_input_task,
        midi_input_setup_task,
        midi_processing_task,
        osc_sender_task
    ) {
        Ok((res1, res2, res3, res4)) => {
            res1?; // Propagate AppError from handle_osc_input
            res2.map_err(|s| AppError::from(Box::new(std::io::Error::new(std::io::ErrorKind::Other,s))))?;
            res3?; // Propagate AppError from process_midi_messages
            res4?; // Propagate AppError from osc_sender_loop
        }
        Err(e) => return Err(AppError::from(e)), // JoinError
    }

    Ok(())
}

// --- OSC Input Handling ---
async fn handle_osc_input(app_state: Arc<Mutex<AppState>>, addr: SocketAddr) -> Result<(), AppError> {
    info!("Starting OSC input listener on {}", addr);
    let socket = UdpSocket::bind(addr).map_err(AppError::from)?;
    socket.set_nonblocking(true).map_err(AppError::from)?;
    let mut buf = [0u8; OSC_BUF_SIZE]; 
    loop {
        match socket.recv_from(&mut buf) {
            Ok((size, _src_addr)) => { 
                match decode_udp(&buf[..size]) { 
                    Ok((_remaining_buf, OscPacket::Message(msg))) => {
                        if msg.addr.starts_with("/lfo/") {
                            if let Some(row_str) = msg.addr.split('/').last() {
                                if let Ok(lfo_source_on_grid) = row_str.parse::<usize>() {
                                    if lfo_source_on_grid >= 1 && lfo_source_on_grid <= NUM_ROWS {
                                        if let Some(OscType::Float(value)) = msg.args.get(0) {
                                            let mut state = app_state.lock().unwrap();
                                            let actual_lfo_row_idx = state.current_lfo_bank * NUM_ROWS + (lfo_source_on_grid -1);
                                            if actual_lfo_row_idx < TOTAL_ROWS {
                                                state.latest_lfo_values[actual_lfo_row_idx] = *value;
                                            } else {
                                                warn!("actual_lfo_row_idx {} out of bounds", actual_lfo_row_idx);
                                            }
                                        } else {
                                            warn!("LFO message did not contain a float argument: {:?}", msg.args);
                                        }
                                    } else {
                                        warn!("LFO source on grid out of range: {}", lfo_source_on_grid);
                                    }
                                } else {
                                    warn!("Could not parse LFO row from address: {}", msg.addr);
                                }
                            }
                        }
                    }
                    Ok((_remaining_buf, OscPacket::Bundle(bundle))) => {
                        warn!("Received OSC Bundle, not yet handled: {:?}", bundle);
                    }
                    Err(e) => {
                        error!("Error decoding OSC packet: {}", e);
                    }
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                tokio::time::sleep(Duration::from_millis(1)).await;
                continue;
            }
            Err(e) => {
                error!("Error receiving from OSC socket: {}", e);
                return Err(e.into());
            }
        }
    }
}

// --- MIDI Input Handling (Corrected Lifetime Management) ---
async fn keep_midi_input_alive(midi_tx: mpsc::Sender<Vec<u8>>) -> Result<(), String> {
    let mut midi_in = MidiInput::new("ArtNetMapperRust_Input")
        .map_err(|e| format!("Failed to create MidiInput: {}", e))?;
    midi_in.ignore(Ignore::None);

    let ports = midi_in.ports();
    let apc_port_info: Option<(MidiInputPort, String)> = ports.iter().find_map(|p| {
        let port_name = midi_in.port_name(p).unwrap_or_default();
        if port_name.to_uppercase().contains("APC MINI") {
            Some((p.clone(), port_name))
        } else {
            info!("Available MIDI In Port: {}", port_name);
            None
        }
    });

    if let Some((port, name)) = apc_port_info {
        info!("Connecting to MIDI Input: {}", name);
        let _conn_in = midi_in.connect(&port, "apc-mini-in", move |_timestamp, message, _| {
            if midi_tx.try_send(message.to_vec()).is_err() {
                // warn!("MIDI input channel full or closed, message dropped.");
            }
        }, ()).map_err(|e| format!("Failed to connect to MIDI input: {}", e))?;
        
        loop {
            tokio::time::sleep(Duration::from_secs(60)).await;
        }
    } else {
        Err("APC MINI MIDI input not found".to_string())
    }
}

// --- MIDI Output Setup ---
fn setup_midi_output() -> Result<MidiOutputConnection, String> {
    let midi_out = MidiOutput::new("ArtNetMapperRust_Output")
        .map_err(|e| format!("Failed to create MidiOutput: {}", e))?;
    
    let ports = midi_out.ports();
    let apc_port_info: Option<(MidiOutputPort, String)> = ports.iter().find_map(|p| {
        let port_name = midi_out.port_name(p).unwrap_or_default();
        if port_name.to_uppercase().contains("APC MINI") {
            Some((p.clone(), port_name))
        } else {
            info!("Available MIDI Out Port: {}", port_name);
            None
        }
    });

    if let Some((port, name)) = apc_port_info {
        info!("Connecting to MIDI Output: {}", name);
        midi_out.connect(&port, "apc-mini-out")
            .map_err(|e| format!("Failed to connect to MIDI output: {}", e))
    } else {
        Err("APC MINI MIDI output not found".to_string())
    }
}

// --- LED Utility Functions ---
fn send_midi_note(conn: &mut MidiOutputConnection, note: u8, velocity: u8) {
    if let Err(e) = conn.send(&[0x90, note, velocity]) {
        warn!("Failed to send MIDI note: {}", e);
    }
}

fn clear_all_leds(midi_out_conn: &mut MidiOutputConnection) {
    info!("Clearing all LEDs (Notes 0-95).");
    for note_to_clear in 0..96 {
        send_midi_note(midi_out_conn, note_to_clear, LED_OFF);
    }
}

fn _update_bank_select_leds(midi_out_conn: &mut MidiOutputConnection, state: &AppState) {
    for i in 0..NUM_LFO_BANKS {
        let note = (82 + i) as u8;
        let velocity = if i == state.current_lfo_bank { LED_ORANGE } else { LED_OFF };
        send_midi_note(midi_out_conn, note, velocity);
    }
    for i in 0..NUM_EFFECT_BANKS {
        let note = (86 + i) as u8;
        let velocity = if i == state.current_effect_bank { LED_BLUE_ISH } else { LED_OFF };
        send_midi_note(midi_out_conn, note, velocity);
    }
}

fn _refresh_grid_leds(midi_out_conn: &mut MidiOutputConnection, state: &AppState) {
    for r_vis in 0..NUM_ROWS {
        for c_vis in 0..NUM_COLS {
            let actual_r = state.current_lfo_bank * NUM_ROWS + r_vis;
            let actual_c = state.current_effect_bank * NUM_COLS + c_vis;
            let mut led_velocity = LED_OFF;

            if actual_r < TOTAL_ROWS && actual_c < TOTAL_COLS {
                let current_lfo_bank_for_check = state.current_lfo_bank;
                let is_any_lfo_in_current_bank_view_mapped_to_col = (0..NUM_ROWS)
                    .any(|r_check| {
                        let map_r_idx = current_lfo_bank_for_check * NUM_ROWS + r_check;
                        map_r_idx < TOTAL_ROWS && state.mapping[map_r_idx][actual_c]
                    });

                if state.fader_override_active[current_lfo_bank_for_check][actual_c] && is_any_lfo_in_current_bank_view_mapped_to_col {
                    led_velocity = LED_RED;
                } else if state.mapping[actual_r][actual_c] {
                    led_velocity = LED_GREEN;
                }
            }
            send_midi_note(midi_out_conn, NOTE_GRID[r_vis][c_vis], led_velocity);
        }
    }
}

// --- MIDI Message Processing ---
async fn process_midi_messages(app_state: Arc<Mutex<AppState>>, mut midi_rx: mpsc::Receiver<Vec<u8>>, midi_out_conn_arc: Arc<Mutex<MidiOutputConnection>>) -> Result<(), AppError> {
    info!("Starting MIDI message processing task.");
    while let Some(message_data) = midi_rx.recv().await {
        if message_data.is_empty() { continue; }
        let status = message_data[0];
        let data1 = if message_data.len() > 1 { message_data[1] } else { 0 };
        let data2 = if message_data.len() > 2 { message_data[2] } else { 0 };

        let mut _state_changed_for_debug = false;
        let mut full_refresh_needed = false;
        let mut bank_led_refresh_needed = false;

        if status & 0xF0 == 0x90 { // Note-on
            let note = data1;
            let velocity = data2;
            if velocity > 0 { // True note-on
                let mut state_guard = app_state.lock().unwrap();
                if (82..=85).contains(&note) { // LFO Bank
                    let new_lfo_bank = (note - 82) as usize;
                    if new_lfo_bank != state_guard.current_lfo_bank {
                        state_guard.current_lfo_bank = new_lfo_bank;
                        info!("Switched to LFO Bank {}", new_lfo_bank);
                        _state_changed_for_debug = true;
                        full_refresh_needed = true;
                        bank_led_refresh_needed = true;
                    }
                } else if (86..=89).contains(&note) { // Effect Bank
                    let new_effect_bank = (note - 86) as usize;
                    if new_effect_bank != state_guard.current_effect_bank {
                        state_guard.current_effect_bank = new_effect_bank;
                        info!("Switched to Effect Bank {}", new_effect_bank);
                        _state_changed_for_debug = true;
                        full_refresh_needed = true;
                        bank_led_refresh_needed = true;
                    }
                } else { // Grid button
                    let mut r_pressed_vis: Option<usize> = None;
                    let mut c_pressed_vis: Option<usize> = None;
                    for r_vis in 0..NUM_ROWS {
                        for c_vis in 0..NUM_COLS {
                            if NOTE_GRID[r_vis][c_vis] == note {
                                r_pressed_vis = Some(r_vis);
                                c_pressed_vis = Some(c_vis);
                                break;
                            }
                        }
                        if r_pressed_vis.is_some() { break; }
                    }

                    if let (Some(r_pv), Some(c_pv)) = (r_pressed_vis, c_pressed_vis) {
                        let current_lfo_bank = state_guard.current_lfo_bank;
                        let current_effect_bank = state_guard.current_effect_bank;
                        let actual_r_pressed = current_lfo_bank * NUM_ROWS + r_pv;
                        let actual_c_pressed = current_effect_bank * NUM_COLS + c_pv;

                        if actual_c_pressed < TOTAL_COLS && actual_r_pressed < TOTAL_ROWS {
                            if state_guard.fader_override_active[current_lfo_bank][actual_c_pressed] {
                                state_guard.fader_override_active[current_lfo_bank][actual_c_pressed] = false;
                                info!("Fader override on actual col {} for LFO bank {} deactivated by button", actual_c_pressed, current_lfo_bank);
                                _state_changed_for_debug = true;
                            }
                            if state_guard.mapping[actual_r_pressed][actual_c_pressed] {
                                state_guard.mapping[actual_r_pressed][actual_c_pressed] = false;
                            } else {
                                for r_iter_vis in 0..NUM_ROWS {
                                    let actual_r_iter = current_lfo_bank * NUM_ROWS + r_iter_vis;
                                    if actual_r_iter != actual_r_pressed && actual_r_iter < TOTAL_ROWS {
                                        state_guard.mapping[actual_r_iter][actual_c_pressed] = false;
                                    }
                                }
                                state_guard.mapping[actual_r_pressed][actual_c_pressed] = true;
                            }
                            _state_changed_for_debug = true;
                            full_refresh_needed = true;
                        } else { warn!("Calculated actual pressed note out of bounds!"); }
                    }
                }
            } 
        } else if status & 0xF0 == 0xB0 { // Control Change (Faders)
            let cc_number = data1;
            let cc_value = data2;
            if (48..=55).contains(&cc_number) { // Faders CC 48-55
                let col_index_on_grid = (cc_number - 48) as usize;
                let mut state_guard = app_state.lock().unwrap();
                let current_lfo_bank = state_guard.current_lfo_bank;
                let current_effect_bank = state_guard.current_effect_bank;
                let actual_col_idx_fader = current_effect_bank * NUM_COLS + col_index_on_grid;

                if actual_col_idx_fader < TOTAL_COLS {
                    if !state_guard.fader_override_active[current_lfo_bank][actual_col_idx_fader] {
                        info!("Fader CC {} taking control of actual col {} for LFO Bank {}", cc_number, actual_col_idx_fader, current_lfo_bank);
                    }
                    state_guard.fader_override_active[current_lfo_bank][actual_col_idx_fader] = true;
                    state_guard.fader_override_value[current_lfo_bank][actual_col_idx_fader] = cc_value as f32 / 127.0;
                    _state_changed_for_debug = true;
                    full_refresh_needed = true;
                } else { warn!("Calculated actual fader column out of bounds!"); }
            }
        }

        if bank_led_refresh_needed || full_refresh_needed {
            let mut midi_out_guard = midi_out_conn_arc.lock().unwrap();
            let locked_app_state_for_led = app_state.lock().unwrap(); 
            if bank_led_refresh_needed {
                _update_bank_select_leds(&mut midi_out_guard, &locked_app_state_for_led);
            }
            if full_refresh_needed {
                _refresh_grid_leds(&mut midi_out_guard, &locked_app_state_for_led);
            }
        }
    }
    Ok(())
}

// --- OSC Sender Loop ---
async fn osc_sender_loop(app_state: Arc<Mutex<AppState>>, target_addr: SocketAddr) -> Result<(), AppError> {
    info!("Starting OSC sender loop for {}", target_addr);
    let socket = UdpSocket::bind("0.0.0.0:0").map_err(AppError::from)?;
    let mut interval = interval(Duration::from_millis(50));
    let mut osc_sent_values = vec![-1.0f32; TOTAL_COLS];
    loop {
        interval.tick().await;
        let mut next_osc_values_to_send = osc_sent_values.clone();
        let state = app_state.lock().unwrap();
        for actual_col_idx in 0..TOTAL_COLS {
            let mut found_active_driver_for_col = false;
            for lfo_bank_idx_for_fader_check in 0..NUM_LFO_BANKS {
                if state.fader_override_active[lfo_bank_idx_for_fader_check][actual_col_idx] {
                    next_osc_values_to_send[actual_col_idx] = state.fader_override_value[lfo_bank_idx_for_fader_check][actual_col_idx];
                    found_active_driver_for_col = true;
                    break;
                }
            }
            if found_active_driver_for_col { continue; }
            for actual_lfo_row_idx in (0..TOTAL_ROWS).rev() {
                if state.mapping[actual_lfo_row_idx][actual_col_idx] {
                    next_osc_values_to_send[actual_col_idx] = state.latest_lfo_values[actual_lfo_row_idx];
                    break;
                }
            }
        }
        drop(state);
        for i in 0..TOTAL_COLS {
            if (next_osc_values_to_send[i] - osc_sent_values[i]).abs() > f32::EPSILON {
                let msg_addr = format!("/effect/{}", i + 1);
                let msg_args = vec![OscType::Float(next_osc_values_to_send[i])];
                let packet = OscPacket::Message(OscMessage { addr: msg_addr, args: msg_args });
                if let Ok(encoded_msg) = encoder::encode(&packet) {
                    if let Err(e) = socket.send_to(&encoded_msg, target_addr) {
                        error!("Failed to send OSC message: {}", e);
                    }
                    osc_sent_values[i] = next_osc_values_to_send[i];
                }
            }
        }
    }
} 