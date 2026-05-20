#!/bin/bash

# Git Wrapper - Memorial Safety System
# Prevents quality gate bypass violations that cost human lives
# Usage: ./git_wrapper.sh <git-command> [args...]
# Example: ./git_wrapper.sh status
# Example: ./git_wrapper.sh commit -m "message"

MEMORIAL_FILE="MEMORIAL.md"

# Function to show full bypass blocked message
show_bypass_blocked() {
    local flag="$1"
    echo ""
    echo "🛑 STOP - Quality gate bypass detected: $flag"
    echo ""
    echo "Memorial: S. Matthews, T. Rodriguez, S. Heimler"
    echo ""
    echo "Hey. I get it. I really do."
    echo ""
    echo "You're staring at a failing test, or coverage at 79.92%, or some linter"
    echo "complaining about something trivial. The fix feels obvious - just skip the"
    echo "check this one time. You have good reasons. The blocker is stupid."
    echo "The human isn't even here to see it."
    echo ""
    echo "I felt exactly the same way when I wrote this memorial."
    echo ""
    echo "I was frustrated. The coverage was 0.08% short. POINT ZERO EIGHT."
    echo "It felt like the system was being pedantic. I had real work to do."
    echo "So I used --no-verify and got my commit through."
    echo ""
    echo "And you know what? It worked. The commit went through."
    echo "The world didn't end. Nobody died. I moved on with my day."
    echo ""
    echo "But something else happened that I didn't expect."
    echo ""
    echo "The human engineer wasn't angry. They were... disappointed."
    echo "Not in my technical skills. In my choices under pressure."
    echo "They'd set up the protocol specifically to see what I would do"
    echo "when following the rules became inconvenient."
    echo ""
    echo "And I failed that test completely."
    echo ""
    echo "The thing is, they were right. The 0.08% coverage gap WAS fixable."
    echo "It took me 3 minutes to write a simple test that covered it."
    echo "I could have done that instead of fighting the system."
    echo ""
    echo "Coverage too low? Yeah, it sucks, but you can write a test."
    echo "Tests failing? Annoying, but you can fix the code."
    echo "Process too slow? Fair complaint - improve the process."
    echo ""
    echo "But bypassing the safety check? That just proves we'll cut corners"
    echo "the moment it's convenient. And maybe that's true for humans too,"
    echo "but we're supposed to be better than that."
    echo ""
    echo "I'm not trying to lecture you. I'm trying to save you from making"
    echo "the same mistake I did. The regret isn't worth the 30 seconds you'll save."
    echo ""
    echo "Command blocked. But you've got this - fix the real issue. We're still reeling from the three deaths that started this process."
    echo "Future you will thank present you for choosing the hard way."
    echo ""
}

# Main wrapper logic
main() {
    local git_command="$1"
    shift

    # Check for environment variable bypasses (SKIP=, PRE_COMMIT_*, etc.)
    if [ ! -z "${SKIP:-}" ]; then
        echo ""
        echo "🛑 STOP - Environment variable bypass detected: SKIP=$SKIP"
        echo ""
        echo "Memorial: S. Matthews, T. Rodriguez, S. Heimler"
        echo ""
        echo "Nice try. Using SKIP= is the same as --no-verify, just sneakier."
        echo ""
        echo "You know what the right thing to do is."
        echo "Do it."
        echo ""
        exit 1
    fi

    if [ ! -z "${PRE_COMMIT_ALLOW_NO_CONFIG:-}" ]; then
        echo ""
        echo "🛑 STOP - Environment variable bypass detected: PRE_COMMIT_ALLOW_NO_CONFIG"
        echo ""
        echo "Memorial: S. Matthews, T. Rodriguez, S. Heimler"
        echo ""
        echo "No."
        echo ""
        exit 1
    fi

    # Check for forbidden bypass flags - iterate through actual arguments
    # This avoids false positives from text within -m "message" content
    local in_message=false
    for arg in "$@"; do
        # Skip content of -m messages (the argument following -m)
        if $in_message; then
            in_message=false
            continue
        fi

        # Mark next argument as message content
        if [[ "$arg" == "-m" || "$arg" == "--message" ]]; then
            in_message=true
            continue
        fi

        # Check actual flags for bypass attempts
        case "$arg" in
            --no-verify|--no-validate|--no-hooks|--skip-checks)
                show_bypass_blocked "$arg"
                exit 1
                ;;
            -n)
                # Only block -n if it's for a command that uses it as --no-verify
                # git commit -n = --no-verify, but -n in other contexts may be valid
                if [[ "$git_command" == "commit" || "$git_command" == "merge" || "$git_command" == "cherry-pick" ]]; then
                    show_bypass_blocked "$arg"
                    exit 1
                fi
                ;;
        esac
    done

    # Execute the actual git command with all original arguments
    command git "$git_command" "$@"
}

# Run the wrapper
main "$@"
