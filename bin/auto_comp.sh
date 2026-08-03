#!/bin/bash
###############################################################################
# Auto Completion for owrap CLI
# This script is meant to be sourced from ~/.bashrc
###############################################################################

_owrap_resolve_home() {
    if [ -n "$OWRAP_HOME" ]; then
        echo "$OWRAP_HOME"
    elif [ -f "$HOME/.owrap_home" ]; then
        cat "$HOME/.owrap_home"
    else
        echo "$HOME/.owrap"
    fi
}

_owrap_complete() {
    local cur="${COMP_WORDS[COMP_CWORD]}"
    local prev="${COMP_WORDS[COMP_CWORD-1]}"

    # Top-level: complete subcommands and top-level flags
    if [[ ${COMP_CWORD} -eq 1 ]]; then
        COMPREPLY=( $(compgen -W "start stop end refresh attach restart setup \
sync read run exec work stat cleanup restore agent finish agents killservers \
f update-area spawn update-home precompact precompact-worker get keepalive p \
wait -a --allow-all" -- "${cur}") )
        return 0
    fi

    local cmd="${COMP_WORDS[1]}"

    # Check if previous word is a flag that expects a value
    case "$prev" in
        --session-file|--input)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        -f|--file)
            COMPREPLY=( $(compgen -f -- "${cur}") )
            return 0
            ;;
        --workspace|--research-root)
            COMPREPLY=( $(compgen -d -- "${cur}") )
            return 0
            ;;
        -p|--prompt-style)
            COMPREPLY=( $(compgen -W "default terse structured code exec \
bullets" -- "${cur}") )
            return 0
            ;;
        --session-id|--session)
            local home
            home="$(_owrap_resolve_home)"
            COMPREPLY=( $(compgen -W "$(ls "$home/sessions/" 2>/dev/null | sed 's/\.session$//')" -- "${cur}") )
            return 0
            ;;
        -i)
            if [[ "$cmd" == "read" || "$cmd" == "agent" || "$cmd" == "run" ]]; then
                COMPREPLY=()
                return 0
            fi
            local home
            home="$(_owrap_resolve_home)"
            COMPREPLY=( $(compgen -W "$(ls "$home/sessions/" 2>/dev/null | sed 's/\.session$//')" -- "${cur}") )
            return 0
            ;;
        --id)
            if [[ "$cmd" == "get" ]]; then
                local kind=""
                local j
                for ((j=2; j<COMP_CWORD; j++)); do
                    local w="${COMP_WORDS[j]}"
                    if [[ ! "$w" =~ ^- ]]; then
                        if [[ -z "$kind" ]]; then
                            kind="$w"
                        else
                            kind="$w"
                            break
                        fi
                    fi
                done
                if [[ "$kind" == "msg" ]] && [ -n "$SESSION_ID" ]; then
                    local home
                    home="$(_owrap_resolve_home)"
                    local msg_dir="$home/docs/sessions/$SESSION_ID/run/output/msg"
                    COMPREPLY=( $(compgen -W "$(ls "$msg_dir" 2>/dev/null | sed 's/^msg_//;s/\.log$//')" -- "${cur}") )
                    return 0
                fi
            fi
            COMPREPLY=()
            return 0
            ;;
        --shell-pid|--name|--msg|-g|--grep|-d|--details|-t|--timeout|-m|--model|--head|--tail)
            COMPREPLY=()
            return 0
            ;;
    esac

    # Determine position in positional arguments (excluding flags)
    local pos_count=0
    local i
    for ((i=2; i<COMP_CWORD; i++)); do
        local word="${COMP_WORDS[i]}"
        if [[ "$word" =~ ^- ]]; then
            case "$word" in
                --shell-pid|--session-file|-i|--session-id|--name|--workspace|\
                --research-root|-f|--file|-g|--grep|-d|--details|--msg|\
                --input|-t|--timeout|-m|--model|--session|-p|--prompt-style|\
                --id|--head|--tail)
                    ((i++))
                    ;;
            esac
        else
            ((pos_count++))
        fi
    done

    # If current word starts with -, offer flags based on subcommand
    if [[ "$cur" == -* ]]; then
        case "$cmd" in
            start)
                COMPREPLY=( $(compgen -W "--shell-pid --session-file \
-i --session-id" -- "${cur}") )
                return 0
                ;;
            stop)
                COMPREPLY=( $(compgen -W "-i --session-id --session-file \
--force" -- "${cur}") )
                return 0
                ;;
            end)
                COMPREPLY=( $(compgen -W "-i --session-id --session-file" \
-- "${cur}") )
                return 0
                ;;
            refresh)
                COMPREPLY=( $(compgen -W "--shell-pid --session-file \
-i --session-id" -- "${cur}") )
                return 0
                ;;
            attach)
                COMPREPLY=( $(compgen -W "--shell-pid" -- "${cur}") )
                return 0
                ;;
            restart)
                COMPREPLY=( $(compgen -W "--shell-pid --session-file \
--force -i --session-id" -- "${cur}") )
                return 0
                ;;
            setup)
                COMPREPLY=( $(compgen -W "--name --workspace \
--research-root --allow-all --oread --no-oread" -- "${cur}") )
                return 0
                ;;
            read)
                COMPREPLY=( $(compgen -W "-f --file -g --grep -s --summarise \
-d --details -i --id --debug -t --timeout --log-time -v --verbose \
--list-styles -p --prompt-style" -- "${cur}") )
                return 0
                ;;
            run)
                COMPREPLY=( $(compgen -W "--msg -i --id --input -t --timeout \
--debug --log-time --add-context -m --model --disablewd" -- "${cur}") )
                return 0
                ;;
            exec|work)
                COMPREPLY=( $(compgen -W "--debug --log-time -m --model \
-t --timeout --disablewd" -- "${cur}") )
                return 0
                ;;
            agent)
                COMPREPLY=( $(compgen -W "-i --id -t --timeout -m --model \
--debug --log-time --clear --disablewd" -- "${cur}") )
                return 0
                ;;
            finish)
                COMPREPLY=( $(compgen -W "--session" -- "${cur}") )
                return 0
                ;;
            killservers)
                COMPREPLY=( $(compgen -W "--session" -- "${cur}") )
                return 0
                ;;
            update-home)
                COMPREPLY=( $(compgen -W "--dry-run --migrate" -- "${cur}") )
                return 0
                ;;
            get)
                COMPREPLY=( $(compgen -W "--session --id --head --tail" \
-- "${cur}") )
                return 0
                ;;
            wait)
                COMPREPLY=( $(compgen -W "--session --timeout" -- "${cur}") )
                return 0
                ;;
            precompact-worker)
                COMPREPLY=( $(compgen -W "--input" -- "${cur}") )
                return 0
                ;;
            *)
                COMPREPLY=()
                return 0
                ;;
        esac
    fi

    # Offer positional completions based on position and subcommand
    case "$cmd" in
        start)
            case $pos_count in
                0|1|2)
                    COMPREPLY=()
                    ;;
                *)
                    COMPREPLY=( $(compgen -W "--shell-pid --session-file \
-i --session-id" -- "${cur}") )
                    ;;
            esac
            ;;
        stop)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "-i --session-id --session-file \
--force" -- "${cur}") ) ;;
            esac
            ;;
        end)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "-i --session-id --session-file" \
-- "${cur}") ) ;;
            esac
            ;;
        refresh)
            case $pos_count in
                0|1)  COMPREPLY=() ;;
                *)    COMPREPLY=( $(compgen -W "--shell-pid --session-file \
-i --session-id" -- "${cur}") ) ;;
            esac
            ;;
        attach)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "--shell-pid" -- "${cur}") ) ;;
            esac
            ;;
        restart)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "--shell-pid --session-file \
--force -i --session-id" -- "${cur}") ) ;;
            esac
            ;;
        setup)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -d -- "${cur}") ) ;;
                *)  COMPREPLY=( $(compgen -W "--name --workspace \
--research-root --allow-all --oread --no-oread" -- "${cur}") ) ;;
            esac
            ;;
        stat)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        cleanup)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -W "trash" -- "${cur}") ) ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        restore)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -W "trash" -- "${cur}") ) ;;
                1)  COMPREPLY=() ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        agent)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "-i --id -t --timeout -m \
--model --debug --log-time --clear --disablewd" -- "${cur}") ) ;;
            esac
            ;;
        finish)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "--session" -- "${cur}") ) ;;
            esac
            ;;
        agents)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -W "clear" -- "${cur}") ) ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        f)
            case $pos_count in
                0)
                    COMPREPLY=( $(compgen -W "tstop estop" -- "${cur}") )
                    COMPREPLY+=( $(compgen -f -- "${cur}") )
                    ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        update-area)
            case $pos_count in
                0|1|2)  COMPREPLY=() ;;
                *)      COMPREPLY=() ;;
            esac
            ;;
        spawn)
            case $pos_count in
                0)  COMPREPLY=() ;;
                *)  COMPREPLY=() ;;
            esac
            ;;
        update-home)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -d -- "${cur}") ) ;;
                *)  COMPREPLY=( $(compgen -W "--dry-run --migrate" \
-- "${cur}") ) ;;
            esac
            ;;
        get)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -W "plan input context session \
memory project area research config home agents output" -- "${cur}") ) ;;
                1)  COMPREPLY=( $(compgen -W "msg task agent exec" \
-- "${cur}") ) ;;
                *)  COMPREPLY=( $(compgen -W "--session --id --head --tail" \
-- "${cur}") ) ;;
            esac
            ;;
        wait)
            case $pos_count in
                0)  COMPREPLY=( $(compgen -W "run exec read msg input" \
-- "${cur}") ) ;;
                1)  COMPREPLY=() ;;
                *)  COMPREPLY=( $(compgen -W "--session --timeout" \
-- "${cur}") ) ;;
            esac
            ;;
        precompact-worker)
            COMPREPLY=( $(compgen -W "--input" -- "${cur}") )
            ;;
        sync|keepalive|p|precompact)
            COMPREPLY=()
            ;;
        *)
            COMPREPLY=()
            ;;
    esac
}

complete -F _owrap_complete owrap

return 0
