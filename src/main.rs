use std::sync::{Arc, Mutex};
use std::net::{SocketAddr, UdpSocket};
use std::time::Duration;
use tokio::time::interval;
use tokio::sync::mpsc; // For channels between MIDI callback and MIDI processing task

use midir::{MidiInput, MidiOutput, Ignore, MidiOutputConnection, MidiInputConnection};
use rosc::{OscPacket, OscMessage, OscType, encoder};
use tracing::{info, warn, error, debug, Level};
use tracing_subscriber::FmtSubscriber;

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

// --- Shared Application State ---
struct AppState {
    current_lfo_bank: usize,
    current_effect_bank: usize,
    mapping: Vec<Vec<bool>>, // [actual_row][actual_col]
    fader_override_active: Vec<Vec<bool>>, // [lfo_bank_idx][actual_col_idx]
    fader_override_value: Vec<Vec<f32>>,  // [lfo_bank_idx][actual_col_idx]
    latest_lfo_values: Vec<f32>, // [actual_lfo_row_idx]
    // OSC sender task might have its own sent_values, or it could be here
    // osc_sent_values: Vec<f32>, // [actual_col_idx]
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
            // osc_sent_values: vec![-1.0; TOTAL_COLS], // Initialize to force send
        }
    }
}

// --- Main Application ---
#[tokio::main]
asynchronous fn main() -> Result<(), Box<dyn std::error::Error>> {
    // Setup logging
    let subscriber = FmtSubscriber::builder()
        .with_max_level(Level::DEBUG) // Adjust level as needed
        .finish();
    tracing::subscriber::set_global_default(subscriber)
        .expect("Setting default subscriber failed");

    info!("Starting ArtNet Mapper in Rust...");

    let app_state = Arc::new(Mutex::new(AppState::new()));

    // --- TODO: Argument Parsing for hosts and ports (similar to argparse in Python) ---
    let in_host_str = "127.0.0.1:9000"; // Placeholder
    let out_host_str = "127.0.0.1:9001"; // Placeholder
    let osc_out_addr: SocketAddr = out_host_str.parse().expect("Failed to parse OSC out address");
    let osc_in_addr: SocketAddr = in_host_str.parse().expect("Failed to parse OSC in address");

    // --- Setup OSC Sender Socket (used by sender task) ---
    // The sender task will create its own socket for sending.
    // Or, we could pass an Arc<UdpSocket> if preferred, but typically tasks manage their resources.

    // --- Spawn Tasks ---
    let osc_input_task = tokio::spawn(handle_osc_input(Arc::clone(&app_state), osc_in_addr));
    let (midi_tx, midi_rx) = mpsc::channel(32); // Channel for MIDI messages
    let midi_input_task = tokio::spawn(setup_midi_input(Arc::clone(&app_state), midi_tx));
    let midi_processing_task = tokio::spawn(process_midi_messages(Arc::clone(&app_state), midi_rx));
    let osc_sender_task = tokio::spawn(osc_sender_loop(Arc::clone(&app_state), osc_out_addr));
    // TODO: MIDI Output setup and LED refresh task/logic

    info!("OSC Input: {}", osc_in_addr);
    info!("OSC Output: {}", osc_out_addr);
    info!("Control mapper running...");

    // Keep the main function alive
    // You might want to await specific tasks if they are critical and should stop the app if they fail.
    tokio::try_join!(
        osc_input_task,
        midi_input_task, // This task might exit after setting up the callback if not careful
        midi_processing_task,
        osc_sender_task
    )?; // Propagate first error

    Ok(())
}

// --- OSC Input Handling ---
asynchronous fn handle_osc_input(app_state: Arc<Mutex<AppState>>, addr: SocketAddr) {
    info!("Starting OSC input listener on {}", addr);
    let socket = UdpSocket::bind(addr).expect("Failed to bind OSC input socket");
    socket.set_nonblocking(true).expect("Failed to set non-blocking on OSC socket");

    let mut buf = [0u8; rosc::decoder::MTU]; // Maximum Transmission Unit for OSC

    loop {
        match socket.recv_from(&mut buf) {
            Ok((size, _src_addr)) => {
                let packet = rosc::decoder::decode(&buf[..size]);
                match packet {
                    Ok(OscPacket::Message(msg)) => {
                        // debug!("OSC Received: {:?}", msg);
                        if msg.addr.starts_with("/lfo/") {
                            if let Some(row_str) = msg.addr.split('/').last() {
                                if let Ok(lfo_source_on_grid) = row_str.parse::<usize>() {
                                    if lfo_source_on_grid >= 1 && lfo_source_on_grid <= NUM_ROWS {
                                        if let Some(OscType::Float(value)) = msg.args.get(0) {
                                            let mut state = app_state.lock().unwrap();
                                            let actual_lfo_row_idx = state.current_lfo_bank * NUM_ROWS + (lfo_source_on_grid -1); // 0-indexed
                                            if actual_lfo_row_idx < TOTAL_ROWS {
                                                state.latest_lfo_values[actual_lfo_row_idx] = *value;
                                                // debug!("LFO {} (actual {}), Bank {} -> {}", lfo_source_on_grid-1, actual_lfo_row_idx, state.current_lfo_bank, *value);
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
                    Ok(OscPacket::Bundle(bundle)) => {
                        // Handle bundles if necessary, could iterate through messages
                        warn!("Received OSC Bundle, not yet handled: {:?}", bundle);
                    }
                    Err(e) => {
                        error!("Error decoding OSC packet: {}", e);
                    }
                }
            }
            Err(ref e) if e.kind() == std::io::ErrorKind::WouldBlock => {
                // No data available right now, yield to the scheduler
                tokio::time::sleep(Duration::from_millis(1)).await; // Small sleep to prevent busy-looping
                continue;
            }
            Err(e) => {
                error!("Error receiving from OSC socket: {}", e);
                break; // Or handle error more gracefully
            }
        }
    }
}

// --- MIDI Input Handling ---
asynchronous fn setup_midi_input(app_state: Arc<Mutex<AppState>>, midi_tx: mpsc::Sender<Vec<u8>>) -> Result<(), String> {
    let mut midi_in = MidiInput::new("ArtNetMapperRust Input")
        .map_err(|e| format!("Failed to create MidiInput: {}", e))?;
    midi_in.ignore(Ignore::None); // Process all message types for now

    let ports = midi_in.ports();
    let mut apc_port_idx: Option<usize> = None;
    for (i, p) in ports.iter().enumerate() {
        let port_name = midi_in.port_name(p).unwrap_or_default();
        info!("MIDI In Port {}: {}", i, port_name);
        if port_name.to_uppercase().contains("APC MINI") {
            apc_port_idx = Some(i);
            break;
        }
    }

    if let Some(idx) = apc_port_idx {
        let port_name = midi_in.port_name(&ports[idx]).unwrap_or_default();
        info!("Connecting to MIDI Input: {}", port_name);

        let _conn_in = midi_in.connect(&ports[idx], "apc-mini-in", move |_timestamp, message, _| {
            // This callback is run by midir's internal thread.
            // It should be lightweight. Send data to our processing task.
            // debug!("MIDI Raw: {:?} (len {})", message, message.len());
            if let Err(e) = midi_tx.try_send(message.to_vec()) {
                 // warn!("Failed to send MIDI message to processing task: {}", e);
                 // This can happen if the channel is full or closed.
                 // Using try_send to be non-blocking for the MIDI callback.
                 // If we expect high MIDI traffic, might need a bounded channel and careful handling
                 // or a way to drop older messages like in the Python queue.
                 // For now, warning if send fails is a start.
            }
        },
        ()).map_err(|e| format!("Failed to connect to MIDI input: {}", e))?;
        // To keep the connection alive, we need to keep `_conn_in` (and `midi_in`) in scope.
        // The current setup_midi_input function will exit, dropping them.
        // This needs to be handled: either move them into a long-lived task or use a different structure.
        // For now, let's just loop to keep it alive for testing, though this is not ideal.
        // A better way is to return the connection object and let the caller manage its lifetime.
        loop {
            tokio::time::sleep(Duration::from_secs(10)).await;
        }
        // Ok(())
    } else {
        Err("APC MINI MIDI input not found".to_string())
    }
}

// --- MIDI Message Processing ---
asynchronous fn process_midi_messages(app_state: Arc<Mutex<AppState>>, mut midi_rx: mpsc::Receiver<Vec<u8>>) {
    info!("Starting MIDI message processing task.");
    // TODO: Setup MIDI Output connection here if it's managed by this task
    // let mut midi_out_conn = match setup_midi_output() { ... }

    while let Some(message_data) = midi_rx.recv().await {
        // debug!("Processing MIDI: {:?}", message_data);
        if message_data.is_empty() {
            continue;
        }

        let status = message_data[0];
        let data1 = if message_data.len() > 1 { message_data[1] } else { 0 };
        let data2 = if message_data.len() > 2 { message_data[2] } else { 0 };

        if status & 0xF0 == 0x90 { // Note-on
            let note = data1;
            let velocity = data2;
            if velocity > 0 { // True note-on
                let mut state = app_state.lock().unwrap();
                // Bank Selection (82-85 for LFO, 86-89 for Effect)
                if (82..=85).contains(&note) { // LFO Bank
                    let new_lfo_bank = (note - 82) as usize;
                    if new_lfo_bank != state.current_lfo_bank {
                        state.current_lfo_bank = new_lfo_bank;
                        info!("Switched to LFO Bank {}", new_lfo_bank);
                        // TODO: Trigger LED update for banks and grid
                        // refresh_all_leds(&mut state, &mut midi_out_conn);
                    }
                } else if (86..=89).contains(&note) { // Effect Bank
                    let new_effect_bank = (note - 86) as usize;
                    if new_effect_bank != state.current_effect_bank {
                        state.current_effect_bank = new_effect_bank;
                        info!("Switched to Effect Bank {}", new_effect_bank);
                        // TODO: Trigger LED update for banks and grid
                    }
                } else { // Grid button
                    // Find which r_vis, c_vis was pressed
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
                        let actual_r_pressed = state.current_lfo_bank * NUM_ROWS + r_pv;
                        let actual_c_pressed = state.current_effect_bank * NUM_COLS + c_pv;

                        if actual_c_pressed >= TOTAL_COLS || actual_r_pressed >= TOTAL_ROWS {
                            warn!("Calculated actual pressed note out of bounds!");
                            continue;
                        }
                        
                        // If fader override is active for current LFO bank's view of this column
                        if state.fader_override_active[state.current_lfo_bank][actual_c_pressed] {
                            state.fader_override_active[state.current_lfo_bank][actual_c_pressed] = false;
                            info!("Fader override on actual col {} for LFO bank {} deactivated by button", 
                                   actual_c_pressed, state.current_lfo_bank);
                        }

                        // Toggle mapping
                        if state.mapping[actual_r_pressed][actual_c_pressed] {
                            state.mapping[actual_r_pressed][actual_c_pressed] = false;
                        } else {
                            // Unmap others in the same LFO bank's view of this column
                            for r_iter_vis in 0..NUM_ROWS {
                                let actual_r_iter = state.current_lfo_bank * NUM_ROWS + r_iter_vis;
                                if actual_r_iter != actual_r_pressed && actual_r_iter < TOTAL_ROWS {
                                    state.mapping[actual_r_iter][actual_c_pressed] = false;
                                }
                            }
                            state.mapping[actual_r_pressed][actual_c_pressed] = true;
                        }
                        // TODO: Trigger full grid LED refresh
                        // _refresh_grid_leds(&mut state, &mut midi_out_conn);
                    }
                }
            }
        } else if status & 0xF0 == 0xB0 { // Control Change (Faders)
            let cc_number = data1;
            let cc_value = data2;
            if (48..=55).contains(&cc_number) { // Faders CC 48-55
                let col_index_on_grid = (cc_number - 48) as usize;
                let mut state = app_state.lock().unwrap();
                let actual_col_idx_fader = state.current_effect_bank * NUM_COLS + col_index_on_grid;
                
                if actual_col_idx_fader < TOTAL_COLS {
                    if !state.fader_override_active[state.current_lfo_bank][actual_col_idx_fader] {
                        info!("Fader CC {} taking control of actual col {} for LFO Bank {}", 
                               cc_number, actual_col_idx_fader, state.current_lfo_bank);
                    }
                    state.fader_override_active[state.current_lfo_bank][actual_col_idx_fader] = true;
                    state.fader_override_value[state.current_lfo_bank][actual_col_idx_fader] = cc_value as f32 / 127.0;
                    // TODO: Trigger grid LED refresh (column might turn RED)
                    // _refresh_grid_leds(&mut state, &mut midi_out_conn);
                } else {
                    warn!("Calculated actual fader column out of bounds!");
                }
            }
        }
    }
}

// --- OSC Sender Loop (20Hz) ---
asynchronous fn osc_sender_loop(app_state: Arc<Mutex<AppState>>, target_addr: SocketAddr) {
    info!("Starting OSC sender loop for {}", target_addr);
    let socket = UdpSocket::bind("0.0.0.0:0").expect("Failed to bind OSC sender socket"); // Bind to any available port
    let mut interval = interval(Duration::from_millis(50)); // 20Hz
    let mut osc_sent_values = vec![-1.0f32; TOTAL_COLS]; // Track last sent values

    loop {
        interval.tick().await;
        let mut next_osc_values_to_send = osc_sent_values.clone(); // Start with last sent (frozen state)
        let state = app_state.lock().unwrap(); // Lock state for reading

        for actual_col_idx in 0..TOTAL_COLS {
            let mut found_active_driver_for_col = false;

            // Priority 1: Fader Overrides
            for lfo_bank_idx_for_fader_check in 0..NUM_LFO_BANKS {
                if state.fader_override_active[lfo_bank_idx_for_fader_check][actual_col_idx] {
                    next_osc_values_to_send[actual_col_idx] = state.fader_override_value[lfo_bank_idx_for_fader_check][actual_col_idx];
                    found_active_driver_for_col = true;
                    break;
                }
            }
            
            if found_active_driver_for_col {
                continue;
            }

            // Priority 2: LFO Mappings
            for actual_lfo_row_idx in (0..TOTAL_ROWS).rev() { // Highest LFO index first
                if state.mapping[actual_lfo_row_idx][actual_col_idx] {
                    next_osc_values_to_send[actual_col_idx] = state.latest_lfo_values[actual_lfo_row_idx];
                    // found_active_driver_for_col = true; // Not strictly needed here as we overwrite anyway
                    break;
                }
            }
            // If no driver, value remains as it was (from osc_sent_values.clone())
        }
        drop(state); // Release lock ASAP

        // Send changed values
        for i in 0..TOTAL_COLS {
            if (next_osc_values_to_send[i] - osc_sent_values[i]).abs() > f32::EPSILON { // Compare floats carefully
                let msg_addr = format!("/effect/{}", i + 1);
                let msg_args = vec![OscType::Float(next_osc_values_to_send[i])];
                let packet = OscPacket::Message(OscMessage { addr: msg_addr, args: msg_args });
                if let Ok(encoded_msg) = encoder::encode(&packet) {
                    if let Err(e) = socket.send_to(&encoded_msg, target_addr) {
                        error!("Failed to send OSC message: {}", e);
                    }
                    osc_sent_values[i] = next_osc_values_to_send[i];
                    // debug!("OSC Sent: /effect/{} = {}", i + 1, next_osc_values_to_send[i]);
                }
            }
        }
    }
}

// --- TODO: MIDI Output and LED Refresh Logic ---
/*
fn setup_midi_output() -> Result<MidiOutputConnection, String> { ... }
fn _update_bank_select_leds(midi_out: &mut MidiOutputConnection, current_lfo_bank: usize, current_effect_bank: usize) { ... }
fn _refresh_grid_leds(midi_out: &mut MidiOutputConnection, app_state: &AppState) { ... }
fn clear_all_leds(midi_out: &mut MidiOutputConnection) { ... }
*/ 